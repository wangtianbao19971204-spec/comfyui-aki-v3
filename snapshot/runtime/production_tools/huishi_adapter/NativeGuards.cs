// Candidate native-call guard for the pinned Huishi GUI. Generated P/Invoke
// clones retain their marshalling contract; Harmony replaces the original call
// with a managed policy gate. This is an API guard, not a process sandbox.
using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Reflection.Emit;
using System.Runtime.ExceptionServices;
using System.Runtime.InteropServices;
using System.Text;
using HarmonyLib;

public static class NativeGuards
{
    private sealed class Call
    {
        internal MethodInfo Original;
        internal MethodInfo Clone;
        internal string Operation;
        internal Action<string, bool> PathGate;
        internal Action<string, string, string> ProcessGate;
        internal Action<string, string> Log;
        internal bool SetLastError;
    }

    private static readonly object Sync = new object();
    private static readonly List<Call> Calls = new List<Call>();
    private static readonly Dictionary<MethodBase, int> Ids = new Dictionary<MethodBase, int>();
    private static readonly Func<IntPtr, Type, object> BoxPointer = CreatePointerBoxer();
    private static readonly HashSet<string> Operations = new HashSet<string>(StringComparer.Ordinal)
    { "CreateProcess", "CreateProcessAsUser", "MoveFileEx", "CreateHardLink", "NtCreateFile" };

    // The caller must first validate the GUI DLL identity. Both policies must
    // throw before a disallowed operation; paths/commands must never be logged.
    // Returning successfully is explicit permission to perform the native call.
    public static int Install(Harmony harmony, Assembly gui,
        Action<string, bool> protectPath, Action<string, string, string> protectProcess,
        Action<string, string> fixedLog)
    {
        if (harmony == null || gui == null || protectPath == null || protectProcess == null || fixedLog == null)
            throw new ArgumentNullException("native_guard_required_contract");
        var targets = gui.GetTypes().SelectMany(t => t.GetMethods(BindingFlags.Public | BindingFlags.NonPublic |
            BindingFlags.Static | BindingFlags.Instance | BindingFlags.DeclaredOnly))
            .Select(m => new { Method = m, Import = m.GetCustomAttribute<DllImportAttribute>() })
            .Where(x => x.Import != null)
            .Select(x => new { x.Method, x.Import, Operation = Operation(x.Import.EntryPoint ?? x.Method.Name) })
            .Where(x => Operations.Contains(x.Operation)).ToArray();
        if (targets.Length == 0) throw new InvalidOperationException("native_guard_targets_missing");

        lock (Sync)
        {
            // Make every clone first. Failure leaves no partially selected calls.
            var staged = new List<Call>();
            foreach (var target in targets)
            {
                if (Ids.ContainsKey(target.Method)) throw new InvalidOperationException("native_guard_duplicate_install");
                Validate(target.Method, target.Import, target.Operation);
                staged.Add(new Call { Original = target.Method, Operation = target.Operation,
                    Clone = target.Operation == "NtCreateFile" ? null : CloneImport(target.Method, target.Import), SetLastError = target.Import.SetLastError,
                    PathGate = protectPath, ProcessGate = protectProcess, Log = fixedLog });
            }
            foreach (var call in staged)
            {
                int id = Calls.Count;
                Calls.Add(call);
                Ids.Add(call.Original, id);
                // Extern methods have no managed body. A transpiler supplies the
                // complete replacement; prefix-only patching is insufficient.
                var patch = harmony.Patch(call.Original,
                    transpiler: new HarmonyMethod(typeof(NativeGuards), nameof(Replace)));
                if (patch == null) throw new InvalidOperationException("native_guard_patch_missing");
                fixedLog("native-guard-installed", call.Operation);
            }
        }
        return targets.Length;
    }

    private static string Operation(string entryPoint)
    {
        if (entryPoint.EndsWith("W", StringComparison.Ordinal) || entryPoint.EndsWith("A", StringComparison.Ordinal))
            return entryPoint.Substring(0, entryPoint.Length - 1);
        return entryPoint;
    }

    private static void Validate(MethodInfo method, DllImportAttribute import, string operation)
    {
        string library = import.Value.ToLowerInvariant();
        if (library.EndsWith(".dll", StringComparison.Ordinal)) library = library.Substring(0, library.Length - 4);
        string expectedLibrary = operation == "NtCreateFile" ? "ntdll"
            : operation == "CreateProcessAsUser" ? "advapi32" : "kernel32";
        if (library != expectedLibrary || !method.IsStatic || method.IsGenericMethod || method.ReturnType.IsByRef
            || method.ReturnType.IsPointer || method.ReturnType.IsByRefLike)
            throw new InvalidOperationException("native_guard_import_contract_changed");
        // The opaque handle operation is replaced by an unconditional throw;
        // it is never marshalled, cloned or allowed to observe pointer arguments.
        if (operation == "NtCreateFile") return;
        foreach (var parameter in method.GetParameters())
        {
            Type type = parameter.ParameterType;
            if (type.IsByRef) type = type.GetElementType();
            // The pinned CreateProcess/AsUser imports use char* environment.
            // Treat it as an opaque address; never read the environment block.
            // By-ref pointers and ref-like values are absent from that contract.
            if ((type.IsPointer && parameter.ParameterType.IsByRef) || type.IsByRefLike || type.ContainsGenericParameters)
                throw new InvalidOperationException("native_guard_unboxable_contract");
        }
        var parameters = method.GetParameters();
        if (operation == "MoveFileEx" || operation == "CreateHardLink")
        {
            if (parameters.Length != 3 || parameters[0].ParameterType != typeof(string)
                || parameters[1].ParameterType != typeof(string) || method.ReturnType != typeof(bool))
                throw new InvalidOperationException("native_guard_path_contract_changed");
        }
        else if (operation == "CreateProcess" || operation == "CreateProcessAsUser")
        {
            int offset = operation == "CreateProcessAsUser" ? 1 : 0;
            if (parameters.Length != 10 + offset || method.ReturnType != typeof(bool)
                || parameters[offset].ParameterType != typeof(string)
                || (parameters[offset + 1].ParameterType != typeof(string)
                    && parameters[offset + 1].ParameterType != typeof(StringBuilder))
                || parameters[offset + 7].ParameterType != typeof(string))
                throw new InvalidOperationException("native_guard_process_contract_changed");
        }
        // NtCreateFile is deliberately never invoked. Its opaque OBJECT_ATTRIBUTES
        // and handle-relative semantics cannot be translated by a string gate.
    }

    private static MethodInfo CloneImport(MethodInfo original, DllImportAttribute import)
    {
        var name = new AssemblyName("Huishi.NativeGuard.Import." + Guid.NewGuid().ToString("N"));
        var assembly = AssemblyBuilder.DefineDynamicAssembly(name, AssemblyBuilderAccess.Run);
        var module = assembly.DefineDynamicModule(name.Name);
        var type = module.DefineType("Import", TypeAttributes.Public | TypeAttributes.Abstract | TypeAttributes.Sealed);
        var parameters = original.GetParameters();
        var method = type.DefineMethod("Invoke",
            MethodAttributes.Public | MethodAttributes.Static | MethodAttributes.HideBySig,
            CallingConventions.Standard, original.ReturnType, parameters.Select(p => p.ParameterType).ToArray());
        method.SetImplementationFlags(import.PreserveSig ? MethodImplAttributes.PreserveSig : (MethodImplAttributes)0);
        // A single DllImport pseudo attribute creates the native mapping and
        // retains every flag. DefinePInvokeMethod followed by another pseudo
        // attribute loses SetLastError on .NET 6; do not use that combination.
        var fields = typeof(DllImportAttribute).GetFields(BindingFlags.Public | BindingFlags.Instance);
        method.SetCustomAttribute(new CustomAttributeBuilder(typeof(DllImportAttribute).GetConstructor(new[] { typeof(string) }),
            new object[] { import.Value }, fields, fields.Select(f => f.GetValue(import)).ToArray()));
        CopyParameter(method.DefineParameter(0, original.ReturnParameter.Attributes, null), original.ReturnParameter);
        for (int i = 0; i < parameters.Length; i++)
            CopyParameter(method.DefineParameter(i + 1, parameters[i].Attributes, parameters[i].Name), parameters[i]);
        var clone = type.CreateType().GetMethod("Invoke");
        var actual = clone.GetCustomAttribute<DllImportAttribute>();
        if (actual.SetLastError != import.SetLastError || actual.CharSet != import.CharSet
            || actual.ExactSpelling != import.ExactSpelling || actual.CallingConvention != import.CallingConvention
            || actual.BestFitMapping != import.BestFitMapping || actual.ThrowOnUnmappableChar != import.ThrowOnUnmappableChar
            || actual.PreserveSig != import.PreserveSig || actual.Value != import.Value || actual.EntryPoint != import.EntryPoint)
            throw new InvalidOperationException("native_guard_clone_import_flags_changed");
        return clone;
    }

    private static void CopyParameter(ParameterBuilder builder, ParameterInfo original)
    {
        // Preserve explicit MarshalAs, In/Out and any other parameter attributes.
        // Constructing attributes from metadata does not execute their constructors.
        foreach (var attribute in original.GetCustomAttributesData())
        {
            var properties = attribute.NamedArguments.Where(a => !a.IsField).ToArray();
            var fields = attribute.NamedArguments.Where(a => a.IsField).ToArray();
            builder.SetCustomAttribute(new CustomAttributeBuilder(attribute.Constructor,
                attribute.ConstructorArguments.Select(AttributeValue).ToArray(),
                properties.Select(a => (PropertyInfo)a.MemberInfo).ToArray(),
                properties.Select(a => AttributeValue(a.TypedValue)).ToArray(),
                fields.Select(a => (FieldInfo)a.MemberInfo).ToArray(),
                fields.Select(a => AttributeValue(a.TypedValue)).ToArray()));
        }
        if (original.HasDefaultValue) builder.SetConstant(original.RawDefaultValue);
    }

    private static object AttributeValue(CustomAttributeTypedArgument value)
    {
        if (value.Value is IList<CustomAttributeTypedArgument> items)
        {
            Type element = value.ArgumentType.GetElementType();
            var array = Array.CreateInstance(element, items.Count);
            for (int i = 0; i < items.Count; i++) array.SetValue(AttributeValue(items[i]), i);
            return array;
        }
        if (value.ArgumentType.IsEnum && value.Value != null) return Enum.ToObject(value.ArgumentType, value.Value);
        return value.Value;
    }

    private static Func<IntPtr, Type, object> CreatePointerBoxer()
    {
        // Reflection accepts System.Reflection.Pointer for a native pointer
        // parameter. Emitting this tiny bridge avoids unsafe source code and
        // never dereferences or copies the pointed-to environment contents.
        var method = new DynamicMethod("BoxOpaquePointer", typeof(object), new[] { typeof(IntPtr), typeof(Type) },
            typeof(NativeGuards).Module, true);
        var il = method.GetILGenerator();
        il.Emit(OpCodes.Ldarg_0);
        il.Emit(OpCodes.Conv_U);
        il.Emit(OpCodes.Ldarg_1);
        il.Emit(OpCodes.Call, typeof(Pointer).GetMethod(nameof(Pointer.Box), BindingFlags.Public | BindingFlags.Static));
        il.Emit(OpCodes.Ret);
        return (Func<IntPtr, Type, object>)method.CreateDelegate(typeof(Func<IntPtr, Type, object>));
    }

    public static object Invoke(int id, object[] args)
    {
        Call call = Calls[id];
        switch (call.Operation)
        {
            case "NtCreateFile":
                BlockOpaque(id);
                throw new InvalidOperationException("native_guard_unreachable");
            case "MoveFileEx":
                call.PathGate(args[0] as string, true);
                if (args[1] != null) call.PathGate(args[1] as string, true);
                break;
            case "CreateHardLink":
                call.PathGate(args[0] as string, false);
                call.PathGate(args[1] as string, false);
                break;
            case "CreateProcess":
            case "CreateProcessAsUser":
                int offset = call.Operation == "CreateProcessAsUser" ? 1 : 0;
                string application = args[offset] as string;
                string command = args[offset + 1] is StringBuilder text ? text.ToString() : args[offset + 1] as string;
                call.ProcessGate(application, command, args[offset + 7] as string);
                break;
        }
        var parameters = call.Original.GetParameters();
        for (int i = 0; i < parameters.Length; i++)
            if (parameters[i].ParameterType.IsPointer)
                args[i] = BoxPointer((IntPtr)args[i], parameters[i].ParameterType);
        object result;
        try { result = call.Clone.Invoke(null, args); }
        catch (TargetInvocationException exception) when (exception.InnerException != null)
        {
            ExceptionDispatchInfo.Capture(exception.InnerException).Throw();
            throw;
        }
        // Reflection's copy-back is managed. Restore the captured last native
        // error before returning to the wrapper/caller, without emitting a log.
        if (call.SetLastError)
        {
            int error = Marshal.GetLastPInvokeError();
            Marshal.SetLastPInvokeError(error);
        }
        return result;
    }

    public static void BlockOpaque(int id)
    {
        Calls[id].Log("blocked-native-write", "opaque-handle-filesystem");
        throw new InvalidOperationException("huishi_adapter_native_handle_filesystem_blocked");
    }

    private static IEnumerable<CodeInstruction> Replace(IEnumerable<CodeInstruction> originalInstructions,
        MethodBase __originalMethod, ILGenerator generator)
    {
        int id = Ids[__originalMethod];
        var method = (MethodInfo)__originalMethod;
        if (Calls[id].Operation == "NtCreateFile")
            return new[] { new CodeInstruction(OpCodes.Ldc_I4, id),
                new CodeInstruction(OpCodes.Call, typeof(NativeGuards).GetMethod(nameof(BlockOpaque))),
                new CodeInstruction(OpCodes.Ldnull), new CodeInstruction(OpCodes.Throw) };
        var parameters = method.GetParameters();
        var instructions = new List<CodeInstruction>();
        var args = generator.DeclareLocal(typeof(object[]));
        var result = generator.DeclareLocal(typeof(object));
        instructions.Add(new CodeInstruction(OpCodes.Ldc_I4, parameters.Length));
        instructions.Add(new CodeInstruction(OpCodes.Newarr, typeof(object)));
        instructions.Add(new CodeInstruction(OpCodes.Stloc, args));
        for (int i = 0; i < parameters.Length; i++)
        {
            Type type = parameters[i].ParameterType;
            bool byRef = type.IsByRef;
            if (byRef) type = type.GetElementType();
            instructions.Add(new CodeInstruction(OpCodes.Ldloc, args));
            instructions.Add(new CodeInstruction(OpCodes.Ldc_I4, i));
            if (byRef && parameters[i].IsOut && !parameters[i].IsIn)
            {
                if (type.IsValueType)
                {
                    var value = generator.DeclareLocal(type);
                    instructions.Add(new CodeInstruction(OpCodes.Ldloca, value));
                    instructions.Add(new CodeInstruction(OpCodes.Initobj, type));
                    instructions.Add(new CodeInstruction(OpCodes.Ldloc, value));
                }
                else instructions.Add(new CodeInstruction(OpCodes.Ldnull));
            }
            else
            {
                instructions.Add(new CodeInstruction(OpCodes.Ldarg, i));
                if (byRef) instructions.Add(new CodeInstruction(type.IsValueType ? OpCodes.Ldobj : OpCodes.Ldind_Ref,
                    type.IsValueType ? type : null));
            }
            if (type.IsPointer)
            {
                instructions.Add(new CodeInstruction(OpCodes.Conv_I));
                instructions.Add(new CodeInstruction(OpCodes.Box, typeof(IntPtr)));
            }
            else if (type.IsValueType) instructions.Add(new CodeInstruction(OpCodes.Box, type));
            instructions.Add(new CodeInstruction(OpCodes.Stelem_Ref));
        }
        instructions.Add(new CodeInstruction(OpCodes.Ldc_I4, id));
        instructions.Add(new CodeInstruction(OpCodes.Ldloc, args));
        instructions.Add(new CodeInstruction(OpCodes.Call, typeof(NativeGuards).GetMethod(nameof(Invoke))));
        instructions.Add(new CodeInstruction(OpCodes.Stloc, result));
        for (int i = 0; i < parameters.Length; i++)
        {
            if (!parameters[i].ParameterType.IsByRef) continue;
            Type type = parameters[i].ParameterType.GetElementType();
            instructions.Add(new CodeInstruction(OpCodes.Ldarg, i));
            instructions.Add(new CodeInstruction(OpCodes.Ldloc, args));
            instructions.Add(new CodeInstruction(OpCodes.Ldc_I4, i));
            instructions.Add(new CodeInstruction(OpCodes.Ldelem_Ref));
            instructions.Add(new CodeInstruction(type.IsValueType ? OpCodes.Unbox_Any : OpCodes.Castclass, type));
            instructions.Add(new CodeInstruction(type.IsValueType ? OpCodes.Stobj : OpCodes.Stind_Ref,
                type.IsValueType ? type : null));
        }
        if (method.ReturnType != typeof(void))
        {
            instructions.Add(new CodeInstruction(OpCodes.Ldloc, result));
            instructions.Add(new CodeInstruction(method.ReturnType.IsValueType ? OpCodes.Unbox_Any : OpCodes.Castclass,
                method.ReturnType));
        }
        instructions.Add(new CodeInstruction(OpCodes.Ret));
        return instructions;
    }
}
