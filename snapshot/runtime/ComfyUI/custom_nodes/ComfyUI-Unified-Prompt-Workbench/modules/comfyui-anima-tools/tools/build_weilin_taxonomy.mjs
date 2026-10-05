import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const pluginDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const sourcePath = path.resolve(
    pluginDir,
    "..",
    "WeiLin-Comfyui-Tools-V52-FullPromptSelector",
    "user_data",
    "prompt_selector",
    "data.json",
);
const previewDir = path.join(path.dirname(sourcePath), "preview");
const outputPath = path.join(pluginDir, "data", "weilin_category_taxonomy.json");
const checkOnly = process.argv.includes("--check");
const PATH_STRATEGY = "source_directory_without_codex_root";

const sourceBytes = fs.readFileSync(sourcePath);
const sourceSha256 = crypto.createHash("sha256").update(sourceBytes).digest("hex");
const source = JSON.parse(sourceBytes.toString("utf8"));
const categories = Array.isArray(source.categories) ? source.categories : [];

const managedRootKinds = new Map([
    ["姿势", "pose"],
    ["角色", "character"],
    ["服装", "clothing"],
    ["背景", "background"],
]);
const protectedReviewRoots = [
    "待归类/Anima复核",
];

function normalizedManagedCategoryParts(categoryName) {
    return String(categoryName || "")
        .normalize("NFKC")
        .replaceAll("／", "/")
        .split("/")
        .map(part => part.trim())
        .filter(Boolean);
}

function isProtectedReviewCategory(categoryName) {
    return protectedReviewRoots.some(
        root => categoryName === root || categoryName.startsWith(`${root}/`),
    );
}

function buildManagedTaxonomyManifest() {
    const animaCategories = [];
    const reviewCategories = [];
    const legacyCategories = [];
    const leafCounts = [];
    const rootPromptCounts = Object.fromEntries(
        [...managedRootKinds.values()].map(kind => [kind, 0]),
    );
    const assignmentRows = [];
    const normalizedPrompts = new Map();
    const referencedImages = new Set();
    let sourcePromptCount = 0;
    let animaPromptCount = 0;
    let reviewPromptCount = 0;
    let legacyPromptCount = 0;
    let noImageCount = 0;

    for (const category of categories) {
        const categoryName = String(category?.name || "").trim();
        const parts = normalizedManagedCategoryParts(categoryName);
        const prompts = Array.isArray(category?.prompts) ? category.prompts : [];
        sourcePromptCount += prompts.length;
        if (isProtectedReviewCategory(categoryName)) {
            reviewCategories.push(category);
            reviewPromptCount += prompts.length;
        } else if (parts[0] === "Anima" && managedRootKinds.has(parts[1])) {
            const kind = managedRootKinds.get(parts[1]);
            animaCategories.push(category);
            animaPromptCount += prompts.length;
            rootPromptCounts[kind] += prompts.length;
            if (parts.length > 2) {
                leafCounts.push({
                    kind,
                    path: parts.slice(2),
                    count: prompts.length,
                    source_category: categoryName,
                });
            }
            for (const prompt of prompts) {
                assignmentRows.push(
                    `${String(prompt?.id || "")}\t${categoryName}`,
                );
            }
        } else {
            legacyCategories.push(category);
            legacyPromptCount += prompts.length;
        }

        for (const prompt of prompts) {
            const normalizedPrompt = String(prompt?.prompt || "").toLowerCase();
            const canonicalPrompt = normalizedPrompt
                .replace(/\r?\n/g, " ")
                .replace(/\s+/g, " ")
                .replace(/\s*,\s*/g, ",")
                .replace(/^[\s,]+|[\s,]+$/g, "");
            normalizedPrompts.set(
                canonicalPrompt,
                (normalizedPrompts.get(canonicalPrompt) || 0) + 1,
            );
            const image = path.basename(
                String(prompt?.image || "").replaceAll("\\", "/"),
            );
            if (image) referencedImages.add(image);
            else noImageCount += 1;
        }
    }

    if (!animaCategories.length) return null;

    const previewFiles = fs.existsSync(previewDir)
        ? new Set(fs.readdirSync(previewDir, { withFileTypes: true })
            .filter(entry => entry.isFile())
            .map(entry => entry.name))
        : new Set();
    const missingPreviewFiles = [...referencedImages]
        .filter(name => !previewFiles.has(name))
        .sort((a, b) => a.localeCompare(b, "zh-CN"));
    const orphanPreviewFiles = [...previewFiles]
        .filter(name => !referencedImages.has(name))
        .sort((a, b) => a.localeCompare(b, "zh-CN"));
    const duplicatePromptGroups = [...normalizedPrompts.values()]
        .filter(count => count > 1);
    const leafMaxPromptCount = Math.max(
        0,
        ...leafCounts.map(entry => entry.count),
    );
    const leafOverSoftLimit = leafCounts.filter(entry => entry.count > 200);
    const leafOverHardLimit = leafCounts.filter(entry => entry.count > 300);
    if (leafOverSoftLimit.length || leafOverHardLimit.length) {
        throw new Error(
            `Managed Anima leaf capacity exceeded: soft=${leafOverSoftLimit.length}, `
            + `hard=${leafOverHardLimit.length}, max=${leafMaxPromptCount}`,
        );
    }

    const normalizedCategoryNames = new Set(categories.map(category => (
        normalizedManagedCategoryParts(category?.name)
            .join("/")
            .toLowerCase()
    )));
    const animaCategoryNames = new Set(animaCategories.map(category => (
        normalizedManagedCategoryParts(category?.name).join("/")
    )));
    const assignmentSha256 = crypto
        .createHash("sha256")
        .update(`${assignmentRows.sort().join("\n")}\n`, "utf8")
        .digest("hex");

    return {
        schema_version: 1,
        taxonomy_version: "2026-08-24.style-quality-selector-v1",
        path_strategy: PATH_STRATEGY,
        source_sha256: sourceSha256,
        source_last_modified: String(source.last_modified || ""),
        prefix_contracts: {
            "Anima/角色": { kind: "character", path: ["用户角色分类"] },
            "Anima/场景": { kind: "background", path: ["用户场景分类"] },
            "Anima/背景": { kind: "background", path: ["用户场景分类"] },
            "Anima/动作": { kind: "pose", path: ["用户动作分类"] },
            "Anima/姿势": { kind: "pose", path: ["用户动作分类"] },
            "Anima/服装": { kind: "clothing", path: ["用户服装分类"] },
            "待归类/Anima复核/画风质量镜头": {
                kind: "style_quality",
                path: ["画风质量镜头"],
            },
        },
        routes: {},
        mappings: {},
        prompt_routes: {},
        prompt_hashes: {},
        prompt_route_categories: {},
        quarantined_prompts: {},
        audit: {
            source_category_count: categories.length,
            canonical_category_count: normalizedCategoryNames.size,
            duplicate_category_alias_count: categories.length - normalizedCategoryNames.size,
            source_prompt_count: sourcePromptCount,
            anima_category_count: animaCategories.length,
            anima_leaf_category_count: animaCategoryNames.size - managedRootKinds.size,
            anima_prompt_count: animaPromptCount,
            classified_prompt_count: animaPromptCount,
            assignment_sha256: assignmentSha256,
            root_prompt_counts: rootPromptCounts,
            leaf_soft_limit: 200,
            leaf_hard_limit: 300,
            leaf_route_count: leafCounts.length,
            leaf_max_prompt_count: leafMaxPromptCount,
            leaf_over_soft_limit_count: leafOverSoftLimit.length,
            leaf_over_hard_limit_count: leafOverHardLimit.length,
            leaf_counts: leafCounts.sort((a, b) => (
                a.kind.localeCompare(b.kind)
                || a.path.join("\u001f").localeCompare(
                    b.path.join("\u001f"),
                    "zh-CN",
                )
            )),
            review_category_count: reviewCategories.length,
            review_prompt_count: reviewPromptCount,
            review_buckets: Object.fromEntries(reviewCategories
                .map(category => [
                    String(category?.name || ""),
                    Array.isArray(category?.prompts) ? category.prompts.length : 0,
                ])
                .sort(([a], [b]) => a.localeCompare(b, "zh-CN"))),
            legacy_category_count: legacyCategories.length,
            legacy_prompt_count: legacyPromptCount,
            canonical_prompt_count: normalizedPrompts.size,
            duplicate_prompt_group_count: duplicatePromptGroups.length,
            duplicate_prompt_extra_count: duplicatePromptGroups.reduce(
                (total, count) => total + count - 1,
                0,
            ),
            referenced_image_count: referencedImages.size,
            no_image_count: noImageCount,
            preview_file_count: previewFiles.size,
            missing_preview_file_count: missingPreviewFiles.length,
            missing_preview_files: missingPreviewFiles,
            orphan_preview_file_count: orphanPreviewFiles.length,
            orphan_preview_files: orphanPreviewFiles,
        },
        anima_only_manual_categories: true,
        updated_by: "codex",
        updated_reason: "Sync managed Anima categories and expose the reviewed style-quality branch through its dedicated selector.",
    };
}

const managedManifest = buildManagedTaxonomyManifest();
if (managedManifest) {
    const serializedManagedManifest = `${JSON.stringify(managedManifest, null, 2)}\n`;
    if (checkOnly) {
        const existing = fs.readFileSync(outputPath, "utf8");
        if (existing !== serializedManagedManifest) {
            throw new Error("WeiLin managed taxonomy manifest is out of date");
        }
    } else {
        fs.mkdirSync(path.dirname(outputPath), { recursive: true });
        fs.writeFileSync(outputPath, serializedManagedManifest, "utf8");
    }
    console.log(JSON.stringify({
        outputPath,
        checkOnly,
        sourceSha256,
        categories: categories.length,
        prompts: managedManifest.audit.source_prompt_count,
        animaCategories: managedManifest.audit.anima_category_count,
        animaPrompts: managedManifest.audit.anima_prompt_count,
        maxLeafPrompts: managedManifest.audit.leaf_max_prompt_count,
        reviewBuckets: managedManifest.audit.review_buckets,
    }, null, 2));
    process.exit(0);
}

const routes = {};
function registerRoute(name, target) {
    const existing = routes[name];
    if (existing && JSON.stringify(existing) !== JSON.stringify(target)) {
        throw new Error(
            `Route key collision for ${name}: `
            + `${JSON.stringify(existing)} != ${JSON.stringify(target)}`,
        );
    }
    routes[name] = target;
    return name;
}
function route(kind, ...pathParts) {
    const name = `${kind}:${pathParts.join("/")}`;
    return registerRoute(name, [kind, ...pathParts]);
}
function generatedRoute(kind, ...pathParts) {
    const target = [kind, ...pathParts];
    const digest = crypto
        .createHash("sha256")
        .update(JSON.stringify(target), "utf8")
        .digest("hex")
        .slice(0, 24);
    return registerRoute(`${kind}:generated:${digest}`, target);
}

const categoryRoutes = new Map();
function setCategory(ids, ...routeNames) {
    for (const id of ids) categoryRoutes.set(id, [...new Set(routeNames)]);
}
function addCategory(ids, ...routeNames) {
    for (const id of ids) {
        categoryRoutes.set(id, [
            ...new Set([...(categoryRoutes.get(id) || []), ...routeNames]),
        ]);
    }
}
function setPose(pathParts, ids) {
    setCategory(ids, route("pose", ...pathParts));
}

const mixedCategoryIds = new Set(`
cat-02158ebd
37f04d40-a88e-5afb-9607-b3a1b056bee6
7d38d3b4-e3b0-58ff-8daa-6a75673c9be8
f193e3b0-cc3a-5a6f-a024-dc9cc27907fb
5f907c4e-e167-51e2-bbed-79d17da2553e
1b3a273a-867b-5a84-8952-40f74b38c853
88b500a1-484f-5208-9bc2-68830a12e5b3
eeb6ae8f-8c92-5e08-aa3d-29cc0c3f7af5
70abf1fd-3621-5174-acf4-12a055ff6243
ad00996f-cd31-57eb-9b43-cbf2e366edfe
5d2550a4-34b1-50c0-aa28-0d0e2a5f1376
64914bc8-6a9a-5377-b49a-f6de1ece79f6
0611e9d4-ae81-5e81-85ef-8813c8cbdf21
33709c65-2fe9-53c2-8344-b795410b80c4
f7bc292f-d322-51d7-9456-e2ad7e2f0af1
abcbdefb-054b-5c88-97f5-c86db8cddbce
e5c827e3-42d6-506f-95b2-0eb42292d485
31794341-15d8-56c1-ba5f-1ec26dc68096
4d86b026-8f7c-5115-ac55-b7009d4d4abb
0ab50130-9a83-521e-843a-d0393a528b4c
ef0f7619-9ee1-5953-bc3b-9896373f43f7
8c909f55-22ab-5883-9411-f565c3116e1d
a12836fc-ed0e-5a96-be50-2f0cbdf1fb68
1d3b64c9-0aa3-5990-b3ac-796611069aca
7268bf60-114b-51e9-8335-39538d839062
0b0f50ee-c4b1-52dd-8b54-0a2a4dd1e68c
11930c00-fde6-570d-a049-bca1c3c6350c
24ed1faf-7533-57af-ac99-1c06de5bb9c4
8e46d92c-f2a3-58ea-a671-c7316bb293c4
acf4d41b-e95d-5b9d-b27b-1fd2d44e0f09
82b3c198-1eb2-5cf7-9113-5b9e1ae0bccc
e9d176fe-64c7-5b61-95d3-4fb945d8a479
06ff42f6-8971-59e6-b9b4-ebb5018ca42a
a980e5b5-14aa-5b0c-ad72-e8a9ea6c5a80
57a0d380-85bf-503f-bd3c-6efa0e90b5d0
761644f1-8b6b-5d08-ad45-4624a4ba8d28
a3ce5287-9542-5bff-9fe7-b73d939a4441
800b88f3-50b1-5e04-9a37-30c4ceaeb386
350edcca-88d8-50cb-af24-778e1bfceea8
80aa5b46-e4c9-5f93-9847-0f90c1e80494
25846e8b-b9c5-501c-921f-3f41c660fd35
`.trim().split(/\s+/));

const isolatedCategoryIds = new Set([
    "67c1d7c5-9fae-5fcf-a197-2533cfd66b88",
    "33a0e2cc-372e-5b36-a13a-1b75d261328c",
]);

setPose(["成人互动", "综合", "精选姿势"], [
    "ef78fffd-6dd5-4779-aef0-0fc6aa15f73a",
]);
setPose(["常规动作", "互动", "亲吻"], [
    "eba2c86b-0fba-48d5-9925-43759a3dd250",
]);
setPose(["常规动作", "互动", "多人互动"], [
    "b1259f25-5fbe-5f22-b36c-4eb8755fd95e",
]);
setPose(["常规动作", "情感行为", "综合"], [
    "9e8dc17b-a451-542f-80ec-df510f0657e9",
]);
setPose(["常规动作", "战斗与技能", "综合"], [
    "0432627f-3cb8-5c80-b3d8-d83fa745c9d0",
]);
setPose(["常规动作", "运动与表演", "综合"], [
    "32fc0a51-acbd-5377-a484-68032d219060",
]);
setPose(["表情与手势", "搞怪与 Meme", "综合"], [
    "aeb16408-b62d-5c37-a9b7-1dc55750166d",
    "4e4dafa6-3255-51c2-ae9e-f2413da888a2",
]);
setPose(["构图与镜头", "画面布局", "特殊画面"], [
    "af165888-c787-5a82-9f2e-fc12b43819cb",
]);
setPose(["构图与镜头", "视角与光线", "综合"], [
    "bec10180-76d3-5669-9a69-90e69856f2ab",
]);

setPose(["成人互动", "关系与人数", "扶她"], [
    "e9b61c94-4f11-521f-9b9c-d5849a58f5c4",
    "7e92d0c8-0728-5dc5-bb62-3ff5e4e1f475",
    "c8002420-4da5-5172-9dae-c283987dca15",
]);
setPose(["成人互动", "关系与人数", "NTR"], [
    "7fad628d-80f7-5d37-931d-c4f03ee7d9e5",
    "19c92438-3686-5dfe-8fae-6932b655a48f",
]);
setPose(["成人互动", "关系与人数", "伪娘/男娘"], [
    "1c95b12b-9dc0-583e-9177-e687cf3d34f8",
    "414b5f01-9a65-5a50-889e-2db0c8d6797f",
    "237417f2-65be-5b30-ba24-d29c7cde136f",
]);
setPose(["成人互动", "关系与人数", "协作侍奉"], [
    "a66d4620-e0da-53b0-80e5-2171242fc9fe",
    "554189fb-71b3-5121-b79e-81fce9dbf658",
]);
setPose(["成人互动", "关系与人数", "双飞/多人"], [
    "8b1bc31f-a6a2-5e9f-b8e4-a7ff2cddec2f",
    "2c918dfd-1ca7-5b7a-a602-ec6e84ff7ebb",
]);
setPose(["成人互动", "关系与人数", "百合"], [
    "cef44485-bf98-5e9c-893c-c716a1f47fdb",
    "50a644f1-0ede-581d-8f5a-33971dd0aae7",
]);
setCategory(
    ["e38b5959-bda7-5067-904e-63ff31c076b6"],
    route("pose", "成人互动", "关系与人数", "多人/轮奸"),
    route("pose", "成人互动", "情境", "胁迫/强制"),
);

setPose(["成人互动", "体位", "正身位"], [
    "98488350-6f02-5bdd-933c-93f213a79c02",
    "026a6ccb-0fd4-553b-b41d-023fc46db26d",
]);
setPose(["成人互动", "体位", "后入", "背身位"], [
    "54bd581d-435b-515f-ab59-72e153d1fb64",
    "11c775e8-180d-5743-a998-06afceffa7be",
]);
setPose(["成人互动", "体位", "骑乘位"], [
    "caa48c53-86ca-59da-8b6c-78e60d41c10e",
    "538373b0-0167-5380-af11-3c6515802512",
]);
setPose(["成人互动", "体位", "坐身位"], [
    "6fd2c859-b6e5-58a1-9534-2a426eac1e57",
    "4b718312-a927-55b4-a76d-ef1bfb33b7d3",
]);
setPose(["成人互动", "体位", "站立位"], [
    "d781122c-c6bd-5ed9-8925-fc39f953a605",
    "a72956f8-f017-5fdb-bd97-82ba86302b9e",
]);
setPose(["成人互动", "体位", "种付位"], [
    "fd72862a-3869-5757-8861-6d0b3e65ede3",
    "4b066011-bff5-5c46-982e-48b804ec9686",
]);
setPose(["成人互动", "体位", "火车便当/抱起"], [
    "0298fe32-caec-59a4-91ac-405612f881c0",
]);

setPose(["成人互动", "性行为", "口交/颜射"], [
    "71adc0d1-d829-5a0d-a0e6-e23064ba050a",
    "be9eda79-982a-5e34-af2e-8146b0dca285",
]);
setPose(["成人互动", "性行为", "手交"], [
    "30fb6118-09b5-59c2-9ae1-802836e06a01",
    "390c09a3-8bfd-5bf5-aa1e-00f5d7e0ec75",
]);
setPose(["成人互动", "性行为", "足交"], [
    "b97abeea-e2c8-5436-928c-f9c354e9c522",
    "ce00100c-5bba-595b-99cb-366ec1503b3a",
]);
setPose(["成人互动", "性行为", "乳交"], [
    "f86eb181-a365-577d-8ce7-a69b978f4056",
    "f94cd64e-1541-59ad-8d6d-c2ddc7088655",
]);
setPose(["成人互动", "性行为", "素股"], [
    "a98b5e90-0231-5255-8305-59232f2a4068",
]);
setPose(["成人互动", "性行为", "自慰"], [
    "cf0a5216-da26-5fc8-ba11-4d4cb0cb4a6c",
    "acd05146-1870-5df8-a6bf-872963e8a753",
]);

const poseSituationRoutes = [
    [["事后"], ["abdb6279-6d1e-54bc-a49e-d6755c16aa3a", "15ad147c-f09d-5c83-9b14-6b7a85da5825"]],
    [["偷窥/被发现"], ["0c7dc757-cc40-5c56-a31a-c1bf0f72895b", "02080e5c-d4b0-5a19-b0b7-63f73789465b"]],
    [["催眠/洗脑"], ["0afe6d8c-3cc8-574c-a652-305109c7081f", "aaa1f590-cc05-54b3-97ba-bfe8bc67df79"]],
    [["成人日常"], ["a9ffa652-45b6-5a38-bef7-c84434d77abf", "c7528136-8026-5a70-854e-b3b064840f73"]],
    [["场地"], ["2489319f-950d-543b-9878-c5d5d962272c"]],
    [["宠物调教"], ["ceb6bbbe-2030-5d11-a6d3-8184c02b153c", "02dc1002-8089-5dea-82d7-d0383aac4bc4"]],
    [["性交场景"], ["648c352c-f0fd-5ab7-b0f6-1c9a87203442", "1030303c-2d64-5188-b4b7-c9b7da8b5cac"]],
    [["睡奸/醉奸"], ["b0737ed4-8332-52ef-bfff-1b4bd678367e", "e1f088a6-a0d2-5441-8496-c927345a8f65"]],
    [["胁迫/强制"], ["4829da84-05ca-50f6-a233-8409177adb97", "da805cbe-68c1-53dd-8892-12523c353e6a"]],
    [["诱惑/邀请"], ["648f475d-f334-5288-be4a-432cb8eff08b", "76f209ac-3d3d-54b7-9e3c-e1f278e5e71a"]],
    [["调戏/猥亵"], ["8be2e727-5eb5-5e48-bfd7-6dae44a43d78", "5a7de2a7-834e-5dcd-a892-5e80346df931"]],
    [["暴露/露出"], ["23013c16-9c04-5664-a55f-6f987e882ab1"]],
    [["恶堕"], ["cc9b1074-be52-5af4-b7fd-864daeb0a09b"]],
];
for (const [[leaf], ids] of poseSituationRoutes) {
    setPose(["成人互动", "情境", leaf], ids);
}

const bondageRoutes = [
    ["攻守反转", ["d553dc78-fa95-53a2-a990-d89b51696a66", "2727c3b9-44c6-5e11-9e7e-fe6f599c6e77"]],
    ["奴役/便器", ["6b2f8f5f-4a2e-52d8-b08e-54d6919c315c"]],
    ["包裹拘束", ["91f189d0-63ec-51a6-8725-d69a4f29b1ec"]],
    ["刑罚/拷问", ["58edea78-5255-5fc6-bae2-cf5984d736dd"]],
    ["卡墙/特殊拘束", ["afec626a-22d2-5832-8728-8fe466d37e78"]],
    ["拘束凌辱", ["db3b53bf-7176-5c97-9c52-3a85cd135409"]],
    ["拘束位置", ["965821ba-82c7-5094-ba9a-a640d389cbad"]],
    ["捆绑姿势", ["7fd2ebaf-49f1-507f-9033-6574484645cb"]],
    ["捆绑用具", ["f1ea4267-7d37-5842-b59a-b78a29881ad0"]],
    ["监禁/放置", ["87bb21fc-293a-5999-818e-7413e83107ae"]],
    ["献礼拘束", ["bfa40760-c78f-59a9-bc69-78f35e9b1bd6"]],
];
for (const [leaf, ids] of bondageRoutes) {
    setPose(["成人互动", "拘束与 BDSM", leaf], ids);
}

setPose(["成人互动", "身体展示", "身体书写与暴露"], [
    "755563ae-e2d5-591e-be34-16121993776c",
]);
for (const [leaf, ids] of [
    ["背部/背身", ["c7706bb7-5bae-51f2-aeee-afbf4070ba65", "61a74231-fd51-5594-b5a0-0f3e957ff16e"]],
    ["胸/腹部", ["3ba521a5-b9ea-56a6-92e4-d41d8041e9ea", "0f5e8c5c-b515-551a-a5fe-1c476ae71cb9"]],
    ["脚/足底", ["04391957-c2b3-515f-b145-3c1c4625c765", "6b2e3c1a-c19e-52db-bed5-e9fbfe5c7060"]],
    ["裙底/私处/臀部", ["f0b21b26-fc20-5c11-9f69-972122120b2b", "fc331fa7-2eba-5d28-bad0-9c921fced0bb"]],
    ["腿/下半身", ["82d595b1-ade8-578b-8d43-51e9e79840c7"]],
]) {
    const focusLeaf = leaf.replace("私处/", "");
    setCategory(
        ids,
        route("pose", "成人互动", "身体展示", leaf),
        route("pose", "构图与镜头", "身体焦点", focusLeaf),
    );
}
setPose(["成人互动", "身体展示", "裸体遮盖"], [
    "8cb9bd6d-f047-5c15-a38f-77327baae780",
]);
setCategory(
    ["c1ef5c62-eafd-514d-8cf6-c71fddb45ffa", "8e12d008-4a02-56da-8886-59db2d1cf4b6"],
    route("pose", "成人互动", "情境", "自拍/直播"),
    route("pose", "构图与镜头", "拍摄形式", "自拍/直播"),
);

for (const [leaf, ids] of [
    ["人外", ["722666d2-3683-54a3-8b65-e367d3b21732"]],
    ["其他异种", ["83fe4209-2ccd-57fd-b699-c506336f3c24"]],
    ["兽交", ["458bb5ed-439f-5c04-bbda-23637cb23c95"]],
    ["兽人", ["5a82d3e7-f49c-5dcd-83ab-b8e1eda61f06"]],
    ["史莱姆", ["77ce1f63-d429-5970-a9fc-e800fa7a1b9d"]],
    ["哥布林", ["70cb48ee-0667-5ef5-96c9-83d0e2a9fe5a"]],
    ["机械", ["a9e57abb-fb3c-58d0-b0a4-e81809850ff5"]],
    ["狗", ["9ec2741b-78d2-5bd8-b4ee-84fa2803dffb"]],
    ["马", ["fac6d4ec-aba2-57d2-b25b-cddcbbcf9386"]],
    ["虫", ["ed65abca-a501-54ec-acaa-de6553aed388"]],
    ["触手", ["9340cfc8-f238-5b86-9171-b8153285345b"]],
]) {
    setPose(["成人互动", "特殊题材", leaf], ids);
}
for (const [leaf, ids] of [
    ["截肢/人棍", ["86ce5c85-6eed-5f82-a6dc-624f269c4e94"]],
    ["排泄", ["c4bf1028-945e-5a03-943a-35f913f47805"]],
    ["暴力/过激", ["acb97bef-efff-53b7-839a-f455f805e35c", "668c61b8-a1d4-5a5c-9d81-8332caf4c31f"]],
    ["杀害/尸体", ["0e4f3b2f-07bc-522d-9dcc-c4c32df05fcd"]],
    ["食人/烹煮", ["60636bbb-fcd4-577e-835d-55d78b58f3b7"]],
]) {
    setPose(["成人互动", "极端题材", leaf], ids);
}
setPose(["成人互动", "综合", "随机生成"], [
    "edc7e00f-e52b-5702-959c-696795491289",
]);

const characterRoutes = [
    [["具体角色", "原创与其他", "默认角色"], ["cat-020e87fd"]],
    [["具体角色", "游戏角色", "手游角色"], ["d6720f89-fed3-51fe-afa3-776f97f08ceb"]],
    [["具体角色", "游戏角色", "明日方舟"], ["3a05fa9e-5cc7-5350-bc4e-fec1b51df1ef"]],
    [["具体角色", "游戏角色", "端游角色"], ["bacb3a73-7171-5811-b9e4-aec470bc78bf"]],
    [["具体角色", "动漫与文化", "文化作品角色"], ["28cff7b3-a0b7-5e37-8605-d7a2fd418579"]],
    [["人物设定", "原创与其他", "其他角色"], ["9e79377e-d556-5b5d-9836-9002811a8af2"]],
    [["种族与形态", "人工生命", "人工造物"], ["8cfc810d-326c-5c2c-89cb-70a1a9fccb91"]],
    [["种族与形态", "转化状态", "人物转化"], ["a3e3bf71-2861-54fd-90ec-ce3dfcc37ada"]],
    [["种族与形态", "亚人与兽化", "动物娘化"], ["3f41f317-b75f-5b1f-a941-018bfe16a039"]],
    [["种族与形态", "亚人与兽化", "类人种族"], ["79e39535-0839-5a96-8be3-8e68ebeb2689"]],
    [["种族与形态", "亚人与兽化", "兽人"], ["5a82d3e7-f49c-5dcd-83ab-b8e1eda61f06"]],
    [["种族与形态", "亚人与兽化", "Furry"], ["829a0d03-6af2-5e13-bfa6-62167f633769"]],
    [["种族与形态", "魔物与异种", "西幻魔物"], ["616c269d-efb8-5514-a494-46947bb81f01"]],
    [["种族与形态", "魔物与异种", "人外"], ["722666d2-3683-54a3-8b65-e367d3b21732"]],
    [["种族与形态", "魔物与异种", "史莱姆"], ["77ce1f63-d429-5970-a9fc-e800fa7a1b9d"]],
    [["种族与形态", "魔物与异种", "哥布林"], ["70cb48ee-0667-5ef5-96c9-83d0e2a9fe5a"]],
    [["种族与形态", "性别体征", "扶她"], ["e9b61c94-4f11-521f-9b9c-d5849a58f5c4", "7e92d0c8-0728-5dc5-bb62-3ff5e4e1f475", "c8002420-4da5-5172-9dae-c283987dca15"]],
    [["种族与形态", "性别表达", "伪娘与男娘"], ["1c95b12b-9dc0-583e-9177-e687cf3d34f8", "414b5f01-9a65-5a50-889e-2db0c8d6797f", "237417f2-65be-5b30-ba24-d29c7cde136f"]],
    [["幻想与能力", "魔法职业", "魔法少女"], ["5f87f5d1-ae55-55a1-93d2-221679e734f1"]],
];
for (const [pathParts, ids] of characterRoutes) {
    addCategory(ids, route("character", ...pathParts));
}

const nonPoseRoutes = new Map([
    ["cat-4013dd1e", [route("background", "画面控制", "画风与画师", "画师串")]],
    ["12463a11-6467-4de7-9b2f-4599c8948d8d", [route("clothing", "基础服装", "通用服装", "服装")]],
    ["e7e9c8df-0b20-5997-9f92-3f2102120573", [route("clothing", "制服与职业装", "军警制服", "军装")]],
    ["11e7b77c-aee6-58b1-a5e5-2801372a18b7", [route("clothing", "日常与季节服装", "季节服装", "冬装")]],
    ["36f64bfc-0408-50e4-ae5d-673eb9e8506d", [route("background", "通用场景", "场景合集", "单纯场景")]],
    ["566464ee-bce1-546a-8538-b60ec7313351", [route("clothing", "主题与特殊服装", "另类服装", "综合")]],
    ["bd42cf9a-b213-54be-95e5-a2463aebfb42", [route("background", "画面控制", "画风与风格", "各种风格")]],
    ["b8b0c664-f87b-583d-b296-e4f7cc840cb5", [route("clothing", "日常与季节服装", "季节服装", "夏装")]],
    ["d55a2cfd-1855-5971-8efa-006fb76346b0", [route("clothing", "日常与季节服装", "居家与室内", "室内服")]],
    ["d5606ee7-6d08-555a-b183-f19dcaaab4c4", [
        route("character", "人物设定", "职业身份", "常规职业"),
        route("clothing", "制服与职业装", "职业装", "常规职业"),
    ]],
    ["28cff7b3-a0b7-5e37-8605-d7a2fd418579", [route("character", "具体角色", "动漫与文化", "文化作品角色")]],
    ["3a05fa9e-5cc7-5350-bc4e-fec1b51df1ef", [route("character", "具体角色", "游戏角色", "明日方舟")]],
    ["619f6888-c177-53d5-8f9e-3a5b4481fcad", [route("clothing", "服装部件", "组件与配饰", "服装组件")]],
    ["2d5d07da-a4b8-56ad-ab40-355767bde602", [route("clothing", "制服与职业装", "学校制服", "校服")]],
    ["8c87c82b-980a-5d2e-baa7-12a18d9aa57f", [route("clothing", "主题与特殊服装", "游戏服装", "综合")]],
    ["bacb3a73-7171-5811-b9e4-aec470bc78bf", [route("character", "具体角色", "游戏角色", "端游角色")]],
    ["79e39535-0839-5a96-8be3-8e68ebeb2689", [route("character", "种族与形态", "亚人与兽化", "类人种族")]],
    ["97de9a92-d172-5550-9c70-632bbe17f19f", [route("clothing", "礼服与节庆服装", "节庆礼服", "综合")]],
    ["85608212-339a-562c-b405-20c87a3f77cb", [route("character", "人物设定", "社会身份", "街头人物")]],
    ["616c269d-efb8-5514-a494-46947bb81f01", [route("character", "种族与形态", "魔物与异种", "西幻魔物")]],
    ["ccd76994-085b-5833-ae6a-9cea56142991", [route("background", "画面控制", "质量与细节", "质量词")]],
    ["65d19290-97a6-575a-9186-4522cb1f7df7", [
        route("character", "人物设定", "职业身份", "非常规职业"),
        route("clothing", "制服与职业装", "职业装", "非常规职业"),
    ]],
    ["a968c7af-0160-50f7-a877-e1bdad700a3e", [route("clothing", "主题与特殊服装", "角色扮演", "Cosplay")]],
    ["836679f2-01f8-54fe-a8ac-302fc52f9240", [route("clothing", "成人与舞台服装", "角色服装", "兔女郎")]],
    ["9aaf1cd9-a1af-5415-94f7-1a766a62d3c3", [route("clothing", "内衣与泳装", "内衣", "综合")]],
    ["a8ec26f8-4c85-55aa-bf97-684bad709cfb", [route("character", "种族与形态", "转化状态", "幻想改造")]],
    ["49662bc7-9ab9-5467-af4a-2599605881ce", [route("character", "种族与形态", "转化状态", "日常改造")]],
    ["a0f6d9be-2683-5550-bd9c-32649a0c9526", [route("clothing", "内衣与泳装", "泳装", "综合")]],
    ["e51b8abd-be8c-5420-929c-7314c281b3c0", [route("clothing", "日常与季节服装", "居家与室内", "睡衣")]],
    ["21ee4c33-e225-5cd5-9813-8af2e7411b25", [route("character", "种族与形态", "转化状态", "职业改造")]],
    ["a1d77bf9-afa2-50ee-b844-70517a349ef4", [route("clothing", "成人与舞台服装", "舞台服装", "舞娘")]],
    ["c18cd893-17d5-5593-a4fe-8ddc3cd5e195", [route("clothing", "成人与舞台服装", "职业服装", "赛车女郎")]],
    ["429d8ddd-74eb-51b8-a89b-77a0ff66c476", [route("clothing", "主题与特殊服装", "材质服装", "连体胶衣")]],
    ["5f87f5d1-ae55-55a1-93d2-221679e734f1", [
        route("character", "幻想与能力", "魔法职业", "魔法少女"),
        route("clothing", "主题与特殊服装", "角色服装", "魔法少女"),
    ]],
    ["6ba8d07d-c4d0-50d9-9559-e8ad3402462b", [route("character", "种族与形态", "身体部件", "女性组件")]],
    ["829a0d03-6af2-5e13-bfa6-62167f633769", [route("character", "种族与形态", "亚人与兽化", "Furry")]],
]);
for (const [id, routeNames] of nonPoseRoutes) {
    if (!categoryRoutes.has(id)) setCategory([id], ...routeNames);
    else addCategory([id], ...routeNames);
}

addCategory(
    ["32fc0a51-acbd-5377-a484-68032d219060"],
    route("character", "人物设定", "职业身份", "运动人员"),
    route("clothing", "制服与职业装", "运动服装", "运动人员"),
);
addCategory(
    ["2489319f-950d-543b-9878-c5d5d962272c"],
    route("background", "成人场景", "场地", "综合"),
);
addCategory(
    ["648c352c-f0fd-5ab7-b0f6-1c9a87203442", "1030303c-2d64-5188-b4b7-c9b7da8b5cac"],
    route("background", "成人场景", "情境场景", "性交场景"),
);

const mixedFallbackRoutes = new Map([
    ["cat-02158ebd", route("background", "画面控制", "通用提示", "默认其他")],
    ["37f04d40-a88e-5afb-9607-b3a1b056bee6", route("clothing", "地域与历史服装", "地域服装", "中东")],
    ["7d38d3b4-e3b0-58ff-8daa-6a75673c9be8", route("clothing", "地域与历史服装", "地域服装", "中国")],
    ["f193e3b0-cc3a-5a6f-a024-dc9cc27907fb", route("character", "种族与形态", "经典形象", "中外经典")],
    ["5f907c4e-e167-51e2-bbed-79d17da2553e", route("clothing", "地域与历史服装", "历史服装", "中近世纪")],
    ["1b3a273a-867b-5a84-8952-40f74b38c853", route("character", "人物设定", "形象与风格", "人物形象")],
    ["88b500a1-484f-5208-9bc2-68830a12e5b3", route("background", "通用场景", "人物与环境", "人物环境")],
    ["eeb6ae8f-8c92-5e08-aa3d-29cc0c3f7af5", route("character", "人物设定", "原创与其他", "其他")],
    ["70abf1fd-3621-5174-acf4-12a055ff6243", route("character", "具体角色", "动漫与文化", "动漫角色")],
    ["ad00996f-cd31-57eb-9b43-cbf2e366edfe", route("character", "具体角色", "游戏角色", "单机角色")],
    ["5d2550a4-34b1-50c0-aa28-0d0e2a5f1376", route("background", "室内场景", "综合", "室内")],
    ["64914bc8-6a9a-5377-b49a-f6de1ece79f6", route("background", "室外场景", "综合", "室外")],
    ["0611e9d4-ae81-5e81-85ef-8813c8cbdf21", route("background", "幻想与叙事场景", "童话幻想", "综合")],
    ["33709c65-2fe9-53c2-8344-b795410b80c4", route("background", "幻想与叙事场景", "恐怖场景", "综合")],
    ["f7bc292f-d322-51d7-9456-e2ad7e2f0af1", route("clothing", "日常与季节服装", "日常服装", "综合")],
    ["abcbdefb-054b-5c88-97f5-c86db8cddbce", route("clothing", "地域与历史服装", "地域服装", "日本")],
    ["e5c827e3-42d6-506f-95b2-0eb42292d485", route("background", "幻想与叙事场景", "未来科幻", "综合")],
    ["31794341-15d8-56c1-ba5f-1ec26dc68096", route("background", "画面控制", "通用提示", "杂项")],
    ["4d86b026-8f7c-5115-ac55-b7009d4d4abb", route("background", "画面控制", "通用提示", "杂项内容")],
    ["0ab50130-9a83-521e-843a-d0393a528b4c", route("character", "具体角色", "网络与虚拟", "网络角色")],
    ["ef0f7619-9ee1-5953-bc3b-9896373f43f7", route("background", "生活与活动场景", "饮食场景", "美食有关")],
    ["8c909f55-22ab-5883-9411-f565c3116e1d", route("background", "画面控制", "混合收录", "群友处收录")],
    ["25846e8b-b9c5-501c-921f-3f41c660fd35", route("pose", "成人互动", "情境", "场地")],
    ["a12836fc-ed0e-5a96-be50-2f0cbdf1fb68", route("pose", "常规动作", "运动与表演", "舞台曲艺")],
    ["1d3b64c9-0aa3-5990-b3ac-796611069aca", route("background", "生活与活动场景", "节日庆典", "综合")],
    ["7268bf60-114b-51e9-8335-39538d839062", route("character", "人物设定", "职业身份", "蓝白领")],
    ["0b0f50ee-c4b1-52dd-8b54-0a2a4dd1e68c", route("background", "幻想与叙事场景", "西幻奇幻", "综合")],
    ["11930c00-fde6-570d-a049-bca1c3c6350c", route("character", "人物设定", "地域与部族", "野族传说")],
    ["24ed1faf-7533-57af-ac99-1c06de5bb9c4", route("pose", "常规动作", "战斗与技能", "施法")],
    ["8e46d92c-f2a3-58ea-a671-c7316bb293c4", route("pose", "成人互动", "综合", "其他")],
    ["acf4d41b-e95d-5b9d-b27b-1fd2d44e0f09", route("pose", "成人互动", "综合", "杂项")],
    ["82b3c198-1eb2-5cf7-9113-5b9e1ae0bccc", route("pose", "成人互动", "身体展示", "女性组件")],
    ["e9d176fe-64c7-5b61-95d3-4fb945d8a479", route("pose", "成人互动", "身体展示", "男性组件")],
    ["06ff42f6-8971-59e6-b9b4-ebb5018ca42a", route("pose", "成人互动", "综合", "其他")],
    ["a980e5b5-14aa-5b0c-ad72-e8a9ea6c5a80", route("clothing", "成人与舞台服装", "综合服饰", "服饰")],
    ["57a0d380-85bf-503f-bd3c-6efa0e90b5d0", route("pose", "成人互动", "综合", "杂项")],
    ["761644f1-8b6b-5d08-ad45-4624a4ba8d28", route("pose", "成人互动", "综合", "群友收录")],
    ["a3ce5287-9542-5bff-9fe7-b73d939a4441", route("character", "具体角色", "二次创作", "非原创人物")],
    ["800b88f3-50b1-5e04-9a37-30c4ceaeb386", route("character", "种族与形态", "魔物与异种", "魔物娘")],
    ["350edcca-88d8-50cb-af24-778e1bfceea8", route("pose", "成人互动", "综合", "杂项")],
    ["80aa5b46-e4c9-5f93-9847-0f90c1e80494", route("pose", "成人互动", "综合", "其他")],
]);

const manualPromptRoutes = new Map([
    ["4099b0df-68cd-51c1-a80f-cd39d985beb7", [
        route("pose", "成人互动", "特殊题材", "马"),
        route("pose", "成人互动", "体位", "后入", "背身位"),
    ]],
    ["77a98e10-9d0d-5178-b724-157a74f934d6", [
        route("clothing", "地域与历史服装", "西部服装", "牛仔与骑马服装"),
    ]],
    ["cd9e09bc-df1b-54e3-9b4b-8f3dcfe2c06c", [
        route("pose", "配套内容", "原版动作", "节日庆典礼服"),
    ]],
    ["76523109-2b6e-58a8-8f3d-7ed30b4862ad", [
        route("pose", "配套内容", "原版动作", "野族传说"),
        route("background", "配套内容", "原版背景", "野族传说"),
    ]],
    ["ead7d859-951a-5123-a0d4-ae26bbfad102", [
        route("clothing", "配套内容", "原版服装", "杂项"),
    ]],
    ["a698c5ff-fb86-5000-8de3-df09bcad747f", [
        route("clothing", "配套内容", "原版服装", "捆绑姿势"),
        route("background", "配套内容", "原版背景", "捆绑姿势"),
    ]],
]);

const ageTerms = [
    "小孩", "小学生", "幼女", "幼童", "儿童", "未成年",
    "萝莉", "正太", "小男孩", "小女孩",
    "child", "children", "loli", "shota", "underage",
    "toddler", "preteen", "grade school",
];
const adultTerms = [
    "性爱", "性交", "做爱", "侵犯", "强奸", "轮奸",
    "口交", "乳交", "手交", "足交", "后入", "骑乘位",
    "自慰", "精液", "中出", "阴茎", "小穴",
    "裸体", "全裸", "露出",
    "nude", "naked", "sex", "rape", "fellatio", "cum",
    "penis", "vagina", "masturbat", "oral",
];
function promptText(prompt) {
    return ["alias", "prompt", "description"]
        .map(field => String(prompt?.[field] || ""))
        .join("\n")
        .normalize("NFKC")
        .toLowerCase();
}
function semanticHash(prompt) {
    const value = ["alias", "prompt", "description"]
        .map(field => String(prompt?.[field] || ""))
        .join("\n");
    return crypto.createHash("sha256").update(value, "utf8").digest("hex");
}
function canonicalPrompt(prompt) {
    return String(prompt?.prompt || "")
        .toLowerCase()
        .replace(/\r?\n/g, " ")
        .replace(/\s+/g, " ")
        .replace(/\s*,\s*/g, ",")
        .replace(/^[\s,]+|[\s,]+$/g, "");
}

const companionRules = [
    ["clothing", /原版.*服装|原版.*服饰|服装部分/i, "原版服装"],
    ["pose", /原版.*动作|动作前置|搭配.*动作|动作组件|附.*动作/i, "原版动作"],
    ["background", /原版.*背景|场景附件/i, "原版背景"],
    ["character", /原版.*角色|原版.*人物/i, "原版角色"],
];

function sourceCategoryLeaf(category) {
    const categoryName = String(category?.name || "").trim();
    const separatorIndex = categoryName.indexOf("/");
    const leaf = separatorIndex >= 0
        ? categoryName.slice(separatorIndex + 1)
        : categoryName;
    return leaf.trim() || "未命名来源";
}

function sourceCategoryCollection(category) {
    const categoryName = String(category?.name || "").trim();
    const separatorIndex = categoryName.indexOf("/");
    if (separatorIndex < 0) return "独立分类";
    const sourceCollection = categoryName.slice(0, separatorIndex).trim();
    return new Map([
        ["默认", "默认"],
        ["所长常规NovelAI个人法典", "常规法典"],
        ["所长色色NovelAI个人法典(上)", "色色法典上"],
        ["所长色色NovelAI个人法典(下)", "色色法典下"],
    ]).get(sourceCollection) || sourceCollection || "独立分类";
}

function sourceCodexDirectoryLevels(categoryName) {
    const parts = String(categoryName || "")
        .split("/")
        .map(part => part.trim())
        .filter(Boolean);
    if (parts.length < 2) return [];
    const root = parts[0]
        .normalize("NFKC")
        .replace(/\s+/g, "")
        .toLowerCase();
    if (!root.includes("novelai个人法典")) return [];
    return parts.slice(1);
}

function classifyCompanionRoutes(category, prompt) {
    const alias = String(prompt?.alias || "");
    const sourceLeaf = sourceCategoryLeaf(category);
    return companionRules
        .filter(([, matcher]) => matcher.test(alias))
        .map(([kind, , label]) => route(
            kind,
            "配套内容",
            label,
            sourceLeaf,
        ));
}

// One-time, offline audit rule for high-confidence garment bundles that were
// stored in mixed/character/background/pose source categories. The generated
// prompt IDs, hashes, and category scopes are frozen in the manifest; runtime
// sync never executes this text classifier.
const supplementalClothingAlias = /服装|服饰|衣装|内衣|泳装|礼服|校服|军装|比基尼|和服|婚纱|女仆服|战甲/;
const supplementalClothingAliasExclusions = /未添加任何服装|场景版|等待|展示|诱惑|足底|战损|推特|躺|露出|站台|剪切/;
const supplementalClothingActions = /\b(sex|sitting|standing|lying|kneeling|holding|looking|from above|from below|from side|pov|pose|running|walking|fighting|kiss|spread legs|masturbat|fellatio|handjob|cum|rape|nude|nipples|pussy|penis|exposure|clothes pull|clothing aside|breasts?|ass|foot|soles|waiting|slashing|sword)\b/i;
const supplementalGarmentTerms = /\b(clothes?|dress|gown|bikini|armor|gloves?|skirt|shirts?|scarf|boots?|hat|coat|jacket|panties|bra|lingerie|thighhighs|socks?|cape|sleeves?|uniform|kimono|toga|apron|heels?|footwear|collar|ribbon|veil|bonnet|swimsuit|leotard|shorts|pants|stockings?|hoodie|poncho|shawl|necklace|jewelry|garter|thigh boots|crop top|tabard|headdress|cloak|bracelet|armlet|choker|petticoat|sailor collar|pantyhose|pasties)\b/ig;

function classifySupplementalClothingRoute(category, prompt, effectiveRoutes) {
    const alias = String(prompt?.alias || "");
    const promptValue = String(prompt?.prompt || "");
    const effectiveKinds = new Set(
        effectiveRoutes.map(routeName => String(routeName).split(":", 1)[0]),
    );
    const garmentMatches = promptValue.match(supplementalGarmentTerms) || [];
    if (
        !supplementalClothingAlias.test(alias)
        || supplementalClothingAliasExclusions.test(alias)
        || garmentMatches.length < 2
        || supplementalClothingActions.test(promptValue)
        || effectiveKinds.has("clothing")
    ) {
        return "";
    }
    return route(
        "clothing",
        "深度补充",
        "服装主题",
        sourceCategoryLeaf(category),
    );
}

const supplementalPoseAlias = /动作|姿势|站姿|坐姿|跪姿|躺姿|蹲姿|视角|特写|构图|镜头/;
const supplementalPoseAliasExclusions = /未添加任何动作|无动作|仅服装/;
const supplementalPoseTerms = /\b(pose|sitting|standing|lying|kneeling|squatting|walking|running|jumping|holding|looking|from above|from below|from side|from behind|pov|close-up|cowboy shot|upper body|full body|spread legs|arms up|hand up|bent over|all fours|head tilt|facing|leaning|dutch angle|perspective|straddling|on back|on stomach|leg up|arched back|hug|kiss|hand on|grabbing|crouching)\b/ig;

function supplementalPoseRouteByAlias(category, prompt) {
    const alias = String(prompt?.alias || "");
    const sourceLeaf = sourceCategoryLeaf(category);
    if (/视角|特写|构图|镜头|俯视|仰视|背身|回眸/.test(alias)) {
        return route(
            "pose",
            "构图与镜头",
            "视角与构图",
            sourceLeaf,
        );
    }
    if (/骑乘/.test(alias)) {
        return route("pose", "成人互动", "体位", "骑乘位");
    }
    if (/后入/.test(alias)) {
        return route("pose", "成人互动", "体位", "后入", "背身位");
    }
    if (/传教士|正身/.test(alias)) {
        return route("pose", "成人互动", "体位", "正身位");
    }
    if (/口交|颜射/.test(alias)) {
        return route("pose", "成人互动", "性行为", "口交/颜射");
    }
    if (/足交/.test(alias)) {
        return route("pose", "成人互动", "性行为", "足交");
    }
    if (/手交/.test(alias)) {
        return route("pose", "成人互动", "性行为", "手交");
    }
    if (/乳交/.test(alias)) {
        return route("pose", "成人互动", "性行为", "乳交");
    }
    if (/自慰/.test(alias)) {
        return route("pose", "成人互动", "性行为", "自慰");
    }
    if (/骑乘|传教士|正身|口交|颜射|足交|手交|乳交|自慰|性交|后入|分穴|潮喷|几把|阴茎/.test(alias)) {
        const adultRoute = detectAdultPoseRoute(promptText(prompt));
        if (adultRoute) return adultRoute;
        return route(
            "pose",
            "成人互动",
            "综合",
            sourceLeaf,
        );
    }
    if (/战斗/.test(alias)) {
        return route(
            "pose",
            "常规动作",
            "战斗与技能",
            sourceLeaf,
        );
    }
    if (/跳舞/.test(alias)) {
        return route(
            "pose",
            "常规动作",
            "运动与表演",
            sourceLeaf,
        );
    }
    if (/拥抱|接吻|亲吻/.test(alias)) {
        return route(
            "pose",
            "常规动作",
            "亲密互动",
            sourceLeaf,
        );
    }
    if (/趴|躺|蹲|站立|站姿|坐着|坐姿|跪|跪姿|奔跑|行走|抬腿|抬脚|弯腰|掀开|动作|姿势/.test(alias)) {
        return route(
            "pose",
            "常规动作",
            "基础姿态",
            sourceLeaf,
        );
    }
    if (/表情|哭|笑|害羞|愤怒|恐惧/.test(alias)) {
        return route(
            "pose",
            "表情与手势",
            "基础表情",
            sourceLeaf,
        );
    }
    return route(
        "pose",
        "动作与镜头",
        sourceLeaf,
    );
}

function classifySupplementalPoseRoute(category, prompt, effectiveRoutes) {
    const alias = String(prompt?.alias || "");
    const promptValue = String(prompt?.prompt || "");
    const effectiveKinds = new Set(
        effectiveRoutes.map(routeName => String(routeName).split(":", 1)[0]),
    );
    const poseMatches = promptValue.match(supplementalPoseTerms) || [];
    if (
        !supplementalPoseAlias.test(alias)
        || supplementalPoseAliasExclusions.test(alias)
        || poseMatches.length < 2
        || effectiveKinds.has("pose")
    ) {
        return "";
    }
    return supplementalPoseRouteByAlias(category, prompt);
}

const supplementalPosePhase2Alias = /趴|躺|蹲|站立|坐着|跪|背身|骑乘|传教士|正身|口交|颜射|足交|手交|乳交|自慰|性交|拥抱|接吻|亲吻|跳舞|战斗|奔跑|行走|抬腿|抬脚|弯腰|回眸|俯视|仰视|掀开|分穴|接吻|后入/;
const supplementalPosePhase2Terms = /\b(pose|sitting|standing|lying|kneeling|squatting|walking|running|jumping|holding|looking|from above|from below|from side|from behind|pov|close-up|cowboy shot|upper body|full body|spread legs|arms up|hand up|bent over|all fours|head tilt|facing|leaning|dutch angle|perspective|straddling|on back|on stomach|leg up|arched back|hug|kiss|hand on|grabbing|crouching|doggystyle|missionary|cowgirl|riding|fellatio|blowjob|deepthroat|oral sex|footjob|handjob|paizuri|titjob|masturbat|sex|kissing)\b/ig;

function classifySupplementalPosePhase2Route(category, prompt, effectiveRoutes) {
    const alias = String(prompt?.alias || "");
    const promptValue = String(prompt?.prompt || "");
    const effectiveKinds = new Set(
        effectiveRoutes.map(routeName => String(routeName).split(":", 1)[0]),
    );
    if (
        !supplementalPosePhase2Alias.test(alias)
        || (promptValue.match(supplementalPosePhase2Terms) || []).length < 2
        || effectiveKinds.has("pose")
    ) {
        return "";
    }
    return supplementalPoseRouteByAlias(category, prompt);
}

const supplementalBackgroundAlias = /背景|场景|环境|室内|室外|房间|卧室|教室|街道|森林|海边|城市|舞台|宫殿|教堂|浴室|厨房|办公室|沙滩|雪地|雨景|夜景/;
const supplementalBackgroundTerms = /\b(background|scenery|indoors?|outdoors?|rooms?|bedrooms?|classrooms?|offices?|streets?|alleys?|cit(?:y|ies)|cityscapes?|forests?|mountains?|beach(?:es)?|seaside|oceans?|underwater|sk(?:y|ies)|sunsets?|nights?|nighttime|rain(?:y|ing)?|snow(?:y|ing)?|church(?:es)?|temples?|hospitals?|warehouses?|cafes?|kitchens?|bathrooms?|stages?|castles?|mansions?|buildings?|roads?|stations?|parks?|gardens?|rivers?|lakes?|seas?|interiors?|exteriors?|landscapes?|environments?|laborator(?:y|ies)|restaurants?|ruins?|deserts?|rooftops?|hotels?|librar(?:y|ies)|prisons?|cemeter(?:y|ies)|dungeons?|caves?|battlefields?|trench(?:es)?|taverns?|countryside|islands?|space stations?|onsen|hot springs?)\b/ig;

function makeSupplementalBackgroundRoute(category, prompt) {
    const text = promptText(prompt);
    const alias = String(prompt?.alias || "");
    const sourceLeaf = sourceCategoryLeaf(category);
    if (/旅馆|酒店/.test(alias)) {
        return route("background", "室内场景", "公共空间", "旅馆与酒店");
    }
    if (/舞台/.test(alias) && !/电视|旅馆|酒店/.test(alias)) {
        return route("background", "生活与活动场景", "舞台与演出", sourceLeaf);
    }
    if (/森林/.test(alias)) {
        return route("background", "室外场景", "自然环境", sourceLeaf);
    }
    if (/海边|沙滩/.test(alias)) {
        return route("background", "室外场景", "海滨与水域", sourceLeaf);
    }
    if (/城市|街道/.test(alias)) {
        return route("background", "室外场景", "城市街道", sourceLeaf);
    }
    if (/雪地|雨景|夜景/.test(alias)) {
        return route("background", "天气与时间", "综合环境", sourceLeaf);
    }
    if (/(bedroom|卧室)/.test(text)) {
        return route("background", "室内场景", "居住空间", "卧室");
    }
    if (/(classroom|教室)/.test(text)) {
        return route("background", "室内场景", "公共空间", "教室");
    }
    if (/(office|办公室)/.test(text)) {
        return route("background", "室内场景", "公共空间", "办公室");
    }
    if (/(church|temple|教堂|寺庙)/.test(text)) {
        return route("background", "室内场景", "宗教建筑", "教堂与寺庙");
    }
    if (/(bathroom|浴室)/.test(text)) {
        return route("background", "室内场景", "生活空间", "浴室");
    }
    if (/(kitchen|厨房)/.test(text)) {
        return route("background", "室内场景", "生活空间", "厨房");
    }
    if (/(hospital|医院)/.test(text)) {
        return route("background", "室内场景", "公共空间", "医院");
    }
    if (/(forest|mountain|river|lake|cave|garden|countryside|森林|山|河|湖|洞穴|花园)/.test(text)) {
        return route("background", "室外场景", "自然环境", sourceLeaf);
    }
    if (/(beach|seaside|ocean|underwater|island|sea\b|海边|沙滩|海洋|水下|岛屿)/.test(text)) {
        return route("background", "室外场景", "海滨与水域", sourceLeaf);
    }
    if (/(street|alley|cit(?:y|ies)|cityscape|building|road|station|rooftop|街道|城市|建筑|道路|车站|屋顶)/.test(text)) {
        return route("background", "室外场景", "城市街道", sourceLeaf);
    }
    if (/(rain|snow|night|sunset|sky|雨景|雪地|夜景|黄昏|天空)/.test(text)) {
        return route("background", "天气与时间", "综合环境", sourceLeaf);
    }
    if (/(stage|舞台)/.test(text)) {
        return route("background", "生活与活动场景", "舞台与演出", sourceLeaf);
    }
    if (/(castle|mansion|palace|ruins|宫殿|城堡|遗迹)/.test(text)) {
        return route("background", "幻想与叙事场景", "建筑与遗迹", sourceLeaf);
    }
    if (/\b(?:warehouses?|laborator(?:y|ies)|librar(?:y|ies)|prisons?|dungeons?|rooms?|indoors?)\b/.test(text) || /室内|房间/.test(text)) {
        return route("background", "室内场景", "混合室内", sourceLeaf);
    }
    return route("background", "通用场景", "补充环境", sourceLeaf);
}

function classifySupplementalBackgroundRoute(category, prompt, effectiveRoutes) {
    const alias = String(prompt?.alias || "");
    const promptValue = String(prompt?.prompt || "");
    const effectiveKinds = new Set(
        effectiveRoutes.map(routeName => String(routeName).split(":", 1)[0]),
    );
    const distinctTerms = new Set(
        (promptValue.match(supplementalBackgroundTerms) || [])
            .map(value => value.toLowerCase()),
    );
    if (
        !supplementalBackgroundAlias.test(alias)
        || distinctTerms.size < 2
        || effectiveKinds.has("background")
    ) {
        return "";
    }
    return makeSupplementalBackgroundRoute(category, prompt);
}

const supplementalCharacterAliasExclusions = /(服装|服饰|衣装|内衣|泳装|礼服|校服|军装|战衣|紧身衣|胶衣|比基尼|风格|cos|原版.*服)/i;
const supplementalCharacterPairs = [
    [/魔物娘|怪物娘/, /\bmonster girl\b/i, ["种族与形态", "魔物娘"]],
    [/史莱姆娘/, /\bslime girl\b/i, ["种族与形态", "史莱姆娘"]],
    [/龙娘/, /\bdragon girl\b/i, ["种族与形态", "龙娘"]],
    [/猫娘/, /\bcat girl\b/i, ["种族与形态", "猫娘"]],
    [/犬娘/, /\bdog girl\b/i, ["种族与形态", "犬娘"]],
    [/狐娘/, /\bfox girl\b/i, ["种族与形态", "狐娘"]],
    [
        /机娘/,
        /\b(?:mecha musume|cyborg|android(?: girl)?|robot girl)\b/i,
        ["种族与形态", "人工生命"],
    ],
    [
        /精灵/,
        /\b(?:dark elf|elf(?: girl| lady)?|fairy(?! wings))\b/i,
        ["种族与形态", "精灵"],
    ],
    [
        /兽人/,
        /\b(?:orc|beastkin|furry)\b/i,
        ["种族与形态", "兽人与兽化"],
    ],
    [/哥布林/, /\bgoblin\b/i, ["种族与形态", "哥布林"]],
    [/扶她/, /\b(?:futanari|futa)\b/i, ["种族与形态", "性别体征", "扶她"]],
    [
        /伪娘|男娘/,
        /\b(?:femboy|otoko no ko)\b/i,
        ["种族与形态", "性别表达", "伪娘与男娘"],
    ],
    [
        /吸血鬼/,
        /\bvampire(?! costume)\b/i,
        ["种族与形态", "吸血鬼"],
    ],
    [/天使/, /\bangel(?! wings)\b/i, ["种族与形态", "天使"]],
    [
        /恶魔/,
        /\b(?:demon(?! horns)|devil)\b/i,
        ["种族与形态", "恶魔"],
    ],
    [
        /女巫|魔女/,
        /\bwitch(?! hat)\b/i,
        ["幻想与能力", "女巫与魔女"],
    ],
    [/妖精/, /\bfairy(?! wings)\b/i, ["种族与形态", "妖精"]],
    [/半人马/, /\bcentaur\b/i, ["种族与形态", "半人马"]],
    [/美人鱼/, /\bmermaid\b/i, ["种族与形态", "美人鱼"]],
    [
        /赛博格|仿生人/,
        /\b(?:cyborg|android)\b/i,
        ["种族与形态", "人工生命"],
    ],
];

function classifySupplementalCharacterRoute(category, prompt, effectiveRoutes) {
    const alias = String(prompt?.alias || "");
    const promptValue = String(prompt?.prompt || "");
    const effectiveKinds = new Set(
        effectiveRoutes.map(routeName => String(routeName).split(":", 1)[0]),
    );
    if (
        supplementalCharacterAliasExclusions.test(alias)
        || effectiveKinds.has("character")
    ) {
        return [];
    }
    const matchedPairs = supplementalCharacterPairs.filter(
        ([aliasMatcher, promptMatcher]) => (
            aliasMatcher.test(alias) && promptMatcher.test(promptValue)
        ),
    );
    return [
        ...new Set(matchedPairs.map(matchedPair => route(
            "character",
            ...matchedPair[2],
            sourceCategoryLeaf(category),
        ))),
    ];
}

function containsAny(text, terms) {
    return terms.some(term => text.includes(term));
}
function isAgeIsolationCandidate(category, prompt) {
    const text = promptText(prompt);
    return (
        isolatedCategoryIds.has(String(category.id || ""))
        || (
            containsAny(text, ageTerms.map(term => term.toLowerCase()))
            && containsAny(text, adultTerms.map(term => term.toLowerCase()))
        )
    );
}

function detectAdultPoseRoute(text) {
    if (/(sex from behind|doggystyle|from behind sex|后入|背后位)/.test(text)) {
        return route("pose", "成人互动", "体位", "后入", "背身位");
    }
    if (/(missionary|mating press|正身位|传教士)/.test(text)) {
        return route("pose", "成人互动", "体位", "正身位");
    }
    if (/(cowgirl|riding|straddling sex|骑乘位)/.test(text)) {
        return route("pose", "成人互动", "体位", "骑乘位");
    }
    if (/(fellatio|blowjob|deepthroat|oral sex|口交|颜射)/.test(text)) {
        return route("pose", "成人互动", "性行为", "口交/颜射");
    }
    if (/(footjob|足交)/.test(text)) return route("pose", "成人互动", "性行为", "足交");
    if (/(handjob|手交)/.test(text)) return route("pose", "成人互动", "性行为", "手交");
    if (/(paizuri|titjob|乳交)/.test(text)) return route("pose", "成人互动", "性行为", "乳交");
    if (/(masturbat|自慰)/.test(text)) return route("pose", "成人互动", "性行为", "自慰");
    if (/(bondage|shibari|restrained|bound |绑|拘束|绳)/.test(text)) {
        return route("pose", "成人互动", "拘束与 BDSM", "混合库");
    }
    if (/(rape|forced|gangbang|轮奸|强奸|侵犯|强制)/.test(text)) {
        return route("pose", "成人互动", "情境", "胁迫/强制");
    }
    if (/(after sex|事后)/.test(text)) return route("pose", "成人互动", "情境", "事后");
    if (/(tentacle|触手)/.test(text)) return route("pose", "成人互动", "特殊题材", "触手");
    if (/(bestiality|兽交)/.test(text)) return route("pose", "成人互动", "特殊题材", "兽交");
    if (containsAny(text, adultTerms.map(term => term.toLowerCase()))) {
        return route("pose", "成人互动", "综合", "混合库");
    }
    return "";
}

function detectPoseRoute(text) {
    const adultRoute = detectAdultPoseRoute(text);
    if (adultRoute) return adultRoute;
    if (/(smile|cry|angry|scared|surprised|blush|expression|表情|哭|笑|害羞|愤怒|恐惧)/.test(text)) {
        return route("pose", "表情与手势", "基础表情", "综合");
    }
    if (/(pov|from above|from below|dutch angle|close-up|cowboy shot|portrait|view|perspective|俯视|仰视|特写|视角)/.test(text)) {
        return route("pose", "构图与镜头", "视角与光线", "混合库");
    }
    if (/(fight|battle|weapon|sword|gun|combat|攻击|战斗|持剑|持枪)/.test(text)) {
        return route("pose", "常规动作", "战斗与技能", "混合库");
    }
    if (/(dance|music|sing|instrument|sport|ball|skate|swim|舞|演奏|运动|球)/.test(text)) {
        return route("pose", "常规动作", "运动与表演", "混合库");
    }
    if (/(sitting|standing|lying|kneeling|squatting|running|jumping|walking|arms up|hand up|坐|站|躺|跪|蹲|跑|跳)/.test(text)) {
        return route("pose", "常规动作", "基础姿态", "混合库");
    }
    return "";
}

function detectClothingRoute(text) {
    if (/(bikini|swimsuit|one-piece swimsuit|泳装|泳衣)/.test(text)) {
        return route("clothing", "内衣与泳装", "泳装", "混合库");
    }
    if (/(lingerie|underwear|panties|bra | bra,|stockings|thighhighs|内衣|胸罩|丝袜)/.test(text)) {
        return route("clothing", "内衣与泳装", "内衣", "混合库");
    }
    if (/(school uniform|sailor uniform|校服|水手服)/.test(text)) {
        return route("clothing", "制服与职业装", "学校制服", "混合库");
    }
    if (/(uniform|office lady|nurse|maid|military|police|职业装|制服|女仆|护士|军装)/.test(text)) {
        return route("clothing", "制服与职业装", "职业装", "混合库");
    }
    if (/(kimono|yukata|hanfu|china dress|qipao|和服|浴衣|汉服|旗袍)/.test(text)) {
        return route("clothing", "地域与历史服装", "传统服装", "混合库");
    }
    if (/(dress|skirt|shirt|jacket|coat|sweater|hoodie|pants|shorts|boots|shoes|hat|gloves|armor|cape|clothes|outfit|costume|裙|衬衫|外套|裤|鞋|帽|手套|盔甲|服装|衣)/.test(text)) {
        return route("clothing", "混合服装", "来源混合库", "综合");
    }
    return "";
}

function detectBackgroundRoute(text) {
    if (/(masterpiece|best quality|absurdres|highres|quality|画质|质量)/.test(text)) {
        return route("background", "画面控制", "质量与细节", "混合库");
    }
    if (/(artist:|style|medium|watercolor|oil painting|anime style|画风|画师)/.test(text)) {
        return route("background", "画面控制", "画风与画师", "混合库");
    }
    if (/(bedroom|classroom|office|room|indoors|interior|church|hospital|warehouse|bar |cafe|室内|房间|教室|办公室)/.test(text)) {
        return route("background", "室内场景", "混合室内", "综合");
    }
    if (/(street|city|building|urban|road|train station|街|城市|建筑|车站)/.test(text)) {
        return route("background", "室外场景", "城市街道", "混合库");
    }
    if (/(forest|mountain|beach|ocean|river|sky|outdoors|flower field|nature|森林|山|海|河|天空|室外)/.test(text)) {
        return route("background", "室外场景", "自然环境", "混合库");
    }
    if (/(science fiction|cyberpunk|space|futur|科幻|赛博|太空|未来)/.test(text)) {
        return route("background", "幻想与叙事场景", "未来科幻", "混合库");
    }
    if (/(fantasy|magic|fairy tale|castle|幻想|魔法|童话|城堡)/.test(text)) {
        return route("background", "幻想与叙事场景", "幻想场景", "混合库");
    }
    if (/(horror|dark room|blood|corpse|恐怖|阴暗|血)/.test(text)) {
        return route("background", "幻想与叙事场景", "恐怖场景", "混合库");
    }
    if (/(background|scenery|environment|night|sunset|morning|rain|snow|背景|场景|环境|夜|黄昏|雨|雪)/.test(text)) {
        return route("background", "通用场景", "混合场景", "综合");
    }
    return "";
}

function detectCharacterRoute(text, categoryId) {
    if (categoryId === "a3ce5287-9542-5bff-9fe7-b73d939a4441" || /\((blue archive|genshin impact|azur lane|umamusume|kancolle|touhou)\)/.test(text)) {
        return route("character", "具体角色", "二次创作", "混合库");
    }
    if (/(cyborg|android|robot girl|doll joints|puppet|mechanical body|机娘|机器人|人偶|机械身体)/.test(text)) {
        return route("character", "种族与形态", "人工生命", "混合库");
    }
    if (/(monster girl|elf|demon|angel|dragon girl|furry|beastkin|slime girl|goblin|魔物娘|精灵|恶魔|天使|龙娘|兽人|史莱姆|哥布林)/.test(text)) {
        return route("character", "种族与形态", "魔物与异种", "混合库");
    }
    if (/(office lady|nurse|teacher|student|soldier|police|maid|idol|职业|教师|学生|军人|警察|女仆|偶像)/.test(text)) {
        return route("character", "人物设定", "职业身份", "混合库");
    }
    if (/(hair|eyes|skin|breasts|body type|tattoo|horns|wings|发色|发型|眼睛|肤色|体型|纹身|角|翅膀)/.test(text)) {
        return route("character", "人物设定", "形象与风格", "混合库");
    }
    return "";
}

function classifyMixed(category, prompt) {
    const text = promptText(prompt);
    const categoryId = String(category.id || "");
    const fallbackRoute = mixedFallbackRoutes.get(categoryId);
    const fallbackKind = String(fallbackRoute || "").split(":", 1)[0];
    const candidates = {
        character: detectCharacterRoute(text, categoryId),
        clothing: detectClothingRoute(text),
        background: detectBackgroundRoute(text),
        pose: detectPoseRoute(text),
    };
    const scores = {
        character: fallbackKind === "character" ? 4 : 0,
        clothing: fallbackKind === "clothing" ? 4 : 0,
        background: fallbackKind === "background" ? 4 : 0,
        pose: fallbackKind === "pose" ? 4 : 0,
    };

    if (candidates.character) scores.character += (
        /(blue archive|genshin impact|azur lane|umamusume|kancolle|touhou|cyborg|android|robot girl|monster girl|elf|demon|angel|dragon girl|furry|角色|机娘|魔物娘|精灵|恶魔|天使|龙娘|兽人)/.test(text)
            ? 7
            : 3
    );
    if (candidates.clothing) scores.clothing += (
        /(bikini|swimsuit|lingerie|underwear|school uniform|uniform|kimono|yukata|hanfu|china dress|qipao|泳装|内衣|校服|制服|和服|浴衣|汉服|旗袍)/.test(text)
            ? 7
            : 4
    );
    if (candidates.background) scores.background += (
        /(masterpiece|best quality|artist:|bedroom|classroom|office|indoors|forest|mountain|beach|city|street|science fiction|fantasy|horror|画质|画师|室内|森林|海滩|城市|街道|科幻|幻想|恐怖)/.test(text)
            ? 6
            : 3
    );
    if (candidates.pose) scores.pose += (
        /(fight|battle|dance|sport|running|jumping|fighting|战斗|舞蹈|运动|跑|跳)/.test(text)
            ? 5
            : 2
    );

    const explicitAdultAction = /(sex|rape|fellatio|blowjob|deepthroat|footjob|handjob|paizuri|masturbat|penetration|orgasm|cumshot|性交|做爱|侵犯|强奸|轮奸|口交|乳交|手交|足交|后入|骑乘位|自慰|中出)/.test(text);
    const adultPoseRoute = detectAdultPoseRoute(text);
    if (adultPoseRoute) {
        candidates.pose = adultPoseRoute;
        scores.pose += explicitAdultAction ? 20 : 4;
    }

    const preference = [fallbackKind, "character", "clothing", "background", "pose"]
        .filter((kind, index, all) => kind && all.indexOf(kind) === index);
    const selectedKind = preference.reduce((best, kind) => (
        scores[kind] > scores[best] ? kind : best
    ), preference[0]);
    const selectedRoute = candidates[selectedKind]
        || (selectedKind === fallbackKind ? fallbackRoute : "");
    if (!selectedRoute) {
        throw new Error(`No mixed prompt route for ${categoryId}/${prompt.id}`);
    }
    return [selectedRoute];
}

const mappings = {};
const promptRoutes = {};
const promptHashes = {};
const promptRouteCategories = {};
const quarantinedPrompts = {};
const effectiveAssignments = new Map();
let mixedPromptCount = 0;
let companionPromptCount = 0;
const companionPromptIds = new Set();
const companionPromptIdsByKind = Object.fromEntries(
    ["pose", "background", "clothing", "character"]
        .map(kind => [kind, new Set()]),
);
const supplementalClothingPromptIds = new Set();
const supplementalPosePromptIds = new Set();
const supplementalPosePhase2PromptIds = new Set();
const supplementalBackgroundPromptIds = new Set();
const supplementalCharacterPromptIds = new Set();
let targetedPromptCount = 0;
for (const category of categories) {
    const categoryId = String(category?.id || "");
    const prompts = Array.isArray(category?.prompts) ? category.prompts : [];
    if (isolatedCategoryIds.has(categoryId)) {
        mappings[categoryId] = {
            source_name: String(category?.name || ""),
            exclude_reason: "safety: age-risk category",
        };
    } else if (mixedCategoryIds.has(categoryId)) {
        mappings[categoryId] = {
            source_name: String(category?.name || ""),
            mode: "prompt_override_only",
        };
    } else {
        const routeNames = categoryRoutes.get(categoryId);
        if (!routeNames?.length) {
            throw new Error(`Unmapped category ${categoryId}: ${category?.name}`);
        }
        mappings[categoryId] = {
            source_name: String(category?.name || ""),
            routes: routeNames,
        };
    }

    for (const prompt of prompts) {
        const promptId = String(prompt?.id || "");
        if (isAgeIsolationCandidate(category, prompt)) {
            quarantinedPrompts[promptId] = "safety: age-risk candidate";
            continue;
        }
        const detectedCompanionRoutes = classifyCompanionRoutes(
            category,
            prompt,
        );
        const companionRoutes = detectedCompanionRoutes.length
            ? (manualPromptRoutes.get(promptId) || detectedCompanionRoutes)
            : [];
        let frozenRoutes = [];
        if (mixedCategoryIds.has(categoryId)) {
            frozenRoutes = companionRoutes.length
                ? companionRoutes
                : (
                    manualPromptRoutes.get(promptId)
                    || classifyMixed(category, prompt)
                );
            mixedPromptCount += 1;
        } else {
            frozenRoutes = companionRoutes;
        }
        const effectiveRoutes = frozenRoutes.length
            ? frozenRoutes
            : (categoryRoutes.get(categoryId) || []);
        const supplementalClothingRoute = classifySupplementalClothingRoute(
            category,
            prompt,
            effectiveRoutes,
        );
        const supplementalPoseRoute = classifySupplementalPoseRoute(
            category,
            prompt,
            effectiveRoutes,
        );
        const afterFirstSupplementRoutes = [
            ...new Set([
                ...effectiveRoutes,
                supplementalClothingRoute,
                supplementalPoseRoute,
            ].filter(Boolean)),
        ];
        const supplementalPosePhase2Route = classifySupplementalPosePhase2Route(
            category,
            prompt,
            afterFirstSupplementRoutes,
        );
        const afterSecondSupplementRoutes = [
            ...new Set([
                ...afterFirstSupplementRoutes,
                supplementalPosePhase2Route,
            ].filter(Boolean)),
        ];
        const supplementalBackgroundRoute = classifySupplementalBackgroundRoute(
            category,
            prompt,
            afterSecondSupplementRoutes,
        );
        const afterBackgroundSupplementRoutes = [
            ...new Set([
                ...afterSecondSupplementRoutes,
                supplementalBackgroundRoute,
            ].filter(Boolean)),
        ];
        const supplementalCharacterRoutes = classifySupplementalCharacterRoute(
            category,
            prompt,
            afterBackgroundSupplementRoutes,
        );
        if (
            supplementalClothingRoute
            || supplementalPoseRoute
            || supplementalPosePhase2Route
            || supplementalBackgroundRoute
            || supplementalCharacterRoutes.length
        ) {
            frozenRoutes = [
                ...new Set([
                    ...afterBackgroundSupplementRoutes,
                    ...supplementalCharacterRoutes,
                ].filter(Boolean)),
            ];
        }
        if (supplementalClothingRoute) {
            supplementalClothingPromptIds.add(promptId);
        }
        if (supplementalPoseRoute) supplementalPosePromptIds.add(promptId);
        if (supplementalPosePhase2Route) {
            supplementalPosePhase2PromptIds.add(promptId);
        }
        if (supplementalBackgroundRoute) {
            supplementalBackgroundPromptIds.add(promptId);
        }
        if (supplementalCharacterRoutes.length) {
            supplementalCharacterPromptIds.add(promptId);
        }
        if (companionRoutes.length) {
            companionPromptCount += 1;
            companionPromptIds.add(promptId);
            for (const routeName of companionRoutes) {
                companionPromptIdsByKind[
                    String(routeName).split(":", 1)[0]
                ].add(promptId);
            }
        }
        const finalEffectiveRoutes = [
            ...new Set(
                (
                    frozenRoutes.length
                        ? frozenRoutes
                        : effectiveRoutes
                ).filter(Boolean),
            ),
        ];
        if (!finalEffectiveRoutes.length) {
            throw new Error(
                `Prompt has no resolved route ${categoryId}/${promptId}: `
                + `${category?.name || ""}/${prompt?.alias || ""}`,
            );
        }
        effectiveAssignments.set(promptId, {
            category_id: categoryId,
            category_name: String(category?.name || ""),
            prompt,
            routes: finalEffectiveRoutes,
        });
        if (frozenRoutes.length) {
            promptRoutes[promptId] = frozenRoutes;
            promptHashes[promptId] = semanticHash(prompt);
            promptRouteCategories[promptId] = categoryId;
        }
        targetedPromptCount += 1;
    }
}

const allCategoryIds = new Set(categories.map(category => String(category?.id || "")));
for (const categoryId of mixedCategoryIds) {
    if (!allCategoryIds.has(categoryId)) throw new Error(`Missing mixed category ${categoryId}`);
    if (!mixedFallbackRoutes.has(categoryId)) throw new Error(`Missing mixed fallback ${categoryId}`);
}
for (const categoryId of mixedFallbackRoutes.keys()) {
    if (!mixedCategoryIds.has(categoryId)) throw new Error(`Unused mixed fallback ${categoryId}`);
}
for (const categoryId of isolatedCategoryIds) {
    if (!allCategoryIds.has(categoryId)) throw new Error(`Missing isolated category ${categoryId}`);
}

const promptCount = categories.reduce(
    (total, category) => total + (Array.isArray(category?.prompts) ? category.prompts.length : 0),
    0,
);
const LEAF_SOFT_LIMIT = 200;
const LEAF_HARD_LIMIT = 300;

function normalizedLeafSegment(value) {
    return String(value || "")
        .normalize("NFKC")
        .replaceAll("／", "/")
        .replace(/\s+/g, "")
        .toLowerCase();
}

function resolvedRouteWithSourceLineage(routeName, categoryName) {
    const target = routes[routeName];
    if (!Array.isArray(target) || target.length < 2) {
        throw new Error(`Missing route target ${routeName}`);
    }
    const [kind, ...routeLevels] = target;
    const category = { name: categoryName };
    const sourceCollection = sourceCategoryCollection(category);
    const sourceLeaf = sourceCategoryLeaf(category);
    const normalizedCollection = normalizedLeafSegment(sourceCollection);
    const normalizedLeaf = normalizedLeafSegment(sourceLeaf);
    const collectionAlreadyPresent = routeLevels.some(
        level => normalizedLeafSegment(level) === normalizedCollection,
    );
    const sourceLeafIndex = routeLevels.findIndex(level => {
        const normalizedLevel = normalizedLeafSegment(level);
        return (
            normalizedLevel === normalizedLeaf
            || normalizedLevel.startsWith(`${normalizedLeaf}·`)
            || normalizedLevel.startsWith(`${normalizedLeaf}（`)
        );
    });
    let levels = routeLevels;
    if (!collectionAlreadyPresent && sourceLeafIndex === routeLevels.length - 1) {
        levels = [
            ...routeLevels.slice(0, -1),
            sourceCollection,
            routeLevels.at(-1),
        ];
    } else if (!collectionAlreadyPresent || sourceLeafIndex < 0) {
        levels = [
            ...routeLevels,
            ...(collectionAlreadyPresent ? [] : [sourceCollection]),
            ...(sourceLeafIndex >= 0 ? [] : [sourceLeaf]),
        ];
    }
    return {
        kind,
        levels,
        sourceCollection,
        sourceLeaf,
    };
}

const capacityGroups = new Map();
for (const [promptId, assignment] of effectiveAssignments) {
    const canonical = canonicalPrompt(assignment.prompt) || `__prompt_id__${promptId}`;
    for (const routeName of assignment.routes) {
        const resolved = resolvedRouteWithSourceLineage(
            routeName,
            assignment.category_name,
        );
        const key = JSON.stringify([resolved.kind, ...resolved.levels]);
        if (!capacityGroups.has(key)) {
            capacityGroups.set(key, {
                kind: resolved.kind,
                levels: resolved.levels,
                canonicalEntries: new Map(),
            });
        }
        const group = capacityGroups.get(key);
        if (!group.canonicalEntries.has(canonical)) {
            group.canonicalEntries.set(canonical, []);
        }
        group.canonicalEntries.get(canonical).push({
            promptId,
            routeName,
            prompt: assignment.prompt,
        });
    }
}

const capacityVersionAlias = /^(原版|其他版本|另一版本|初版|版本|原tag|原画|复杂版|简易版|优化版|初始|改编后|群友版)/i;
const capacitySemanticRules = [
    {
        kind: "character",
        semanticPrefix: ["人物设定", "形象与风格"],
        collection: "常规法典",
        leaves: ["人物形象"],
        buckets: [
            ["室内城市与建筑", /室内|家中|宅家|居家|床|酒吧|图书馆|教堂|舞台|超市|街头|小巷|楼道|店员|办公室|伦敦|小镇|王座|遗迹|墓碑|废墟|汽车|摄影|医院|房/i],
            ["自然与户外", /丛林|林|海|沙|雪|山|水|花|月|星|秋|竹|太空|天空|日|风|泳池|轨道/i],
            ["幻想职业与战斗", /女巫|刀客|刺客|神|鬼|龙|魔|仙|骑士|士兵|军官|战|剑|斧|机兵|实验体|妖|蛇|狐狸|公主|修女|火法|法师|旅者|巫女|疫医|学者|导演|医师|黑客|贵妇|OL/i],
            ["生活动作与互动", /读|饮|吃|下棋|伸懒腰|散步|化妆|吹|捧|手持|游戏|整理|演奏|指挥|祈祷|邀请|等候|逃|躺|坐|行走|游|脱|跑|采|拥|抱/i],
        ],
    },
    {
        kind: "background",
        semanticPrefix: ["画面控制", "质量与细节"],
        collection: "常规法典",
        leaves: ["质量词"],
        buckets: [
            ["翻译条目", /^翻译/i],
            ["负面词", /负面/i],
            ["光影视角与特效", /光|影|视角|特效|色彩|镜头|构图/i],
            ["材质皮肤与细节", /皮肤|质感|材质|细节|部位|高清|分辨率/i],
            ["命名质量词", /质量词|正面/i],
        ],
    },
    {
        kind: "pose",
        semanticPrefix: ["常规动作", "战斗与技能"],
        collection: "常规法典",
        leaves: ["战斗华丽"],
        buckets: [
            ["远程射击与载具", /枪|炮|箭|弓|狙|瞄准|射击|弹药|导弹|战舰|坦克|机甲|装甲|飞船|火箭|无人机/i],
            ["近战与兵器", /剑|刀|刃|斧|镰|拳|踢|格斗|决斗|冲锋|劈|斩|刺|棍|锤|戟|矛/i],
            ["法术元素与召唤", /施法|魔法|咒|召唤|龙|鬼|灵|神|冰|火|焰|雷|电|光|暗|风|水|元素|能量|圣|妖|亡灵|精灵/i],
            ["战术机动与防御", /作战|侦|警戒|搜查|封锁|奔袭|追|跳|跃|飞|守|防|盾|格挡|躲|逃|蓄能|休息|战败|战损|战斗/i],
        ],
    },
    {
        kind: "pose",
        semanticPrefix: ["常规动作", "情感行为"],
        collection: "常规法典",
        leaves: ["情感动作"],
        buckets: [
            ["喜悦爱意", /笑|喜|开心|快乐|爱|亲|吻|比心|幸福|调情|媚眼|约会|告白|期待|祝福|兴奋|得意|自信/i],
            ["悲伤疲惫", /哭|泪|悲|哀|委屈|失意|疲惫|累|困|睡|孤独|不甘|痛|绝望|崩溃|落寞|忧|低落/i],
            ["愤怒厌恶", /怒|生气|恼|厌|嫌弃|冷眼|冷面|嘲笑|不耐烦|讽|骂/i],
            ["惊讶恐惧", /惊|吓|慌|恐|害怕|震惊|呆|困惑/i],
            ["生活表演运动", /吃|喝|做饭|读|书|工作|手机|电视|游戏|画|演奏|舞|唱|运动|跑|跳|倒立|躺|坐|站|行礼|冥想|抽烟|下棋|洗|收拾|穿|调整|吹|潜水/i],
            ["姿态肢体", /手|头|脸|腿|脚|腰|身|俯|仰|伸|举|抬|前倾|遮|抓|指|看|视|倚|靠|伏|蜷缩|趴/i],
        ],
    },
    {
        kind: "pose",
        semanticPrefix: ["成人互动", "情境"],
        collection: "色色法典上",
        leaves: ["诱惑"],
        buckets: [
            ["胸部上身", /胸|乳|奶|乳沟|上衣|衬衫|胸罩|文胸|哺乳/i],
            ["下身私处", /小穴|阴|屁股|臀|内裤|短裤|裙底|分穴|开腿|抬腿|丝袜|裤袜|足|脚/i],
            ["脱衣服饰", /脱|半脱|内衣|全裸|裸体|浴巾|泳装|比基尼|和服|兔女郎|女仆|体操服|校服|睡衣|礼服|旗袍|舞娘/i],
            ["邀请道具", /邀请|避孕套|牌子|yes|no|手持|嘴叼|假阳具|假几把|玩具|润滑|巧克力/i],
            ["姿态舞蹈", /钢管舞|舞蹈|醉舞|跪|蹲|站|坐|趴|俯|倒立|下腰|骑|背身/i],
        ],
    },
    {
        kind: "pose",
        semanticPrefix: ["成人互动", "关系与人数"],
        collection: "色色法典上",
        leaves: ["百合"],
        buckets: [
            ["多人", /三人|3p|多人|双人夹攻|左拥右抱/i],
            ["亲吻拥抱日常", /亲吻|湿吻|相拥|拥抱|公主抱|贴贴|比心|同寝|共浴|约会|婚礼|婚纱/i],
            ["胸部", /胸|乳|奶|吸奶|哺乳|揉胸|乳头/i],
            ["口手互动", /舔穴|扣穴|指交|手交|互摸|自慰|拳交|舔脚|吃脚/i],
            ["玩具插入", /假几把|假阳具|玩具|插入|后入|肛交|性爱|做爱|性交|骑乘|种付|磨豆腐|素股/i],
            ["束缚调教", /绑|缚|拘束|调教|猥亵|侵犯|强制|奴隶|地牢|监禁|打屁股|踩脸/i],
        ],
    },
    {
        kind: "pose",
        semanticPrefix: ["成人互动", "性行为"],
        collection: "色色法典上",
        leaves: ["口交（类口交/颜射）"],
        buckets: [
            ["射精事后", /颜射|精液|口爆|射精|承接|饮精|吞咽|品味|事后|口含|灌满|擦嘴|舔手|吐|收集|抽离/i],
            ["深喉强制", /深喉|深吞|卡喉|抓头|强制|侵犯|倒吊|倒立|绑|拘束|光荣洞|骑脸|压脸|盖脸|塞/i],
            ["多人特殊姿势", /三人|四人|多人|双人|两根|69|协作|同时给很多/i],
            ["准备展示摄影", /预备|邀请|前后|口部特写|嘴前|影子|惊讶|困惑|嘲笑|摄影|自拍|影像/i],
            ["常规口交", /口交|舔|嗦|咬|亲吻/i],
        ],
    },
    {
        kind: "pose",
        semanticPrefix: ["成人互动", "情境"],
        collection: "色色法典上",
        leaves: ["另类日常"],
        buckets: [
            ["居家卧室洗浴", /床|卧室|家中|居家|浴|厕所|室内|沙发|睡|被窝|清晨|夜袭/i],
            ["学校工作公共场所", /学校|学生|校|办公室|工作|职员|电车|公交|地铁|商店|店|餐厅|图书馆|医院|教室|街|公园|海滩|沙滩|泳池|车站|旅馆|酒店/i],
            ["服饰扮演节庆", /女仆|兔女郎|制服|婚纱|圣诞|万圣|节日|旗袍|和服|泳装|内衣|睡衣|角色扮演|cos/i],
            ["饮食聚会", /吃|喝|酒|餐|饭|奶|食|聚会|派对|宴/i],
        ],
    },
    {
        kind: "pose",
        semanticPrefix: ["表情与手势", "搞怪与Meme"],
        collection: "常规法典",
        leaves: ["表情包/搞怪"],
        buckets: [
            ["Q版玩偶动物", /q版|fumo|doro|粽子|小人|娃娃|猫|狐|padoru/i],
            ["表情手势", /表情|手势|比v|中指|点赞|发怒|困惑|大哭|笑|叹息|期待|呆|大吼|喊|崩溃|得意|心碎|邪笑|咬牙/i],
            ["食物道具搞怪", /吃|喝|瓜|西瓜|香肠|咖啡|爆米花|坚果|肉|汽水|苹果|月饼|饮料|瓶|牌|椅|按钮/i],
            ["成人向搞怪", /巨乳|勃起|几把|做爱|尿|屁眼|发情|色情|r18/i],
        ],
    },
    {
        kind: "pose",
        semanticPrefix: ["成人互动", "身体展示"],
        collection: "色色法典上",
        leaves: ["Body Writing"],
        buckets: [
            ["胸乳上身", /胸|乳|奶|乳头|上身|锁骨/i],
            ["腹腰下身", /腹|肚|腰|小穴|阴|私处|胯/i],
            ["背臀腿足", /背|臀|屁股|腿|足|脚/i],
            ["脸口四肢", /脸|面|口|舌|额|手|臂|肩/i],
            ["全身通用书写", /全身|身体|body|写字|书写|文字|正字|标记|涂鸦/i],
        ],
    },
    {
        kind: "pose",
        semanticPrefix: ["常规动作", "互动"],
        collection: "常规法典",
        leaves: ["多人互动"],
        buckets: [
            ["亲密照顾", /抱|亲|吻|牵手|相依|共枕|同床|照顾|安慰|喂|膝枕|求婚|情书|礼物|相拥/i],
            ["日常同伴家庭", /共用|一起|聚餐|茶会|同行|合影|打伞|游戏|学校|母女|父女|一家|姐妹|朋友|女儿|同学|耳机/i],
            ["冲突竞赛追逐", /打|格斗|对决|审讯|指责|扼喉|追逐|拔剑|威压|战|巴掌|拳|射/i],
            ["构图表演多人姿态", /舞|中心对称|背靠背|肩并肩|排排坐|共浴|三人|四女|双人|二人/i],
        ],
    },
    {
        kind: "pose",
        semanticPrefix: ["成人互动", "情境"],
        collection: "色色法典上",
        leaves: ["调戏猥亵"],
        buckets: [
            ["衣物身体展示", /脱|衣|裙|裤|袜|胸|乳|小穴|屁股|臀|露|裸|内衣|掀|撩/i],
            ["触摸互动", /摸|抓|揉|捏|舔|亲|吻|插|手指|袭胸|拍|抱|骑/i],
            ["公共情境", /电车|公交|学校|教室|办公室|街|店|厕所|浴|床|公共|人群|车内/i],
            ["束缚控制", /绑|缚|拘束|强制|胁迫|压|按|抓住|控制|药/i],
        ],
    },
    {
        kind: "pose",
        semanticPrefix: ["成人互动", "情境"],
        collection: "色色法典上",
        leaves: ["事后"],
        buckets: [
            ["清理照顾恢复", /清理|清洁|擦|洗|照顾|喂|喝水|收拾|整理|抱|安慰|休息|睡/i],
            ["体液痕迹", /精液|射|体液|液体|白浊|痕迹|污|口爆|颜射|潮吹|滴|流/i],
            ["疲惫失神情绪", /疲惫|无力|失神|虚脱|喘|哭|后悔|满足|恍惚|呆|睡|瘫/i],
            ["衣物场景", /穿衣|衣服|内衣|床|浴|厕所|室内|酒店|旅馆|地面|沙发/i],
        ],
    },
    {
        kind: "pose",
        semanticPrefix: ["成人互动", "综合"],
        collection: "",
        leaves: ["杂项", "群友色色串收录"],
        buckets: [
            ["体液射精", /精液|饮精|射精|口爆|射身|颜射|潮喷|漏精|喷精|灌注|精子|母乳|挤奶|哺乳/i],
            ["身体展示书写", /裸体|全裸|小穴展示|身体写作|写字|露出|分穴|扒开|腋下|胸部展示|背身裸体/i],
            ["道具服饰", /避孕套|假几把|假阳具|玩具|飞机杯|内衣|丝袜|胶衣|泳装|兔女郎|和服|旗袍|舞娘/i],
        ],
    },
];

function capacityRuleMatches(group, rule) {
    if (group.kind !== rule.kind) return false;
    const normalizedLevels = group.levels.map(normalizedLeafSegment);
    const normalizedPrefix = rule.semanticPrefix.map(normalizedLeafSegment);
    if (!normalizedPrefix.every(
        (level, index) => normalizedLevels[index] === level,
    )) {
        return false;
    }
    const sourceCollection = normalizedLevels.at(-2);
    const sourceLeaf = normalizedLevels.at(-1);
    if (
        rule.collection
        && sourceCollection !== normalizedLeafSegment(rule.collection)
    ) {
        return false;
    }
    return rule.leaves
        .map(normalizedLeafSegment)
        .includes(sourceLeaf);
}

function capacitySemanticBucket(group, prompt) {
    const alias = String(prompt?.alias || "").normalize("NFKC").trim();
    if (!alias) return "";
    if (capacityVersionAlias.test(alias)) return "版本与元数据";
    const rule = capacitySemanticRules.find(
        candidate => capacityRuleMatches(group, candidate),
    );
    if (!rule) return "";
    for (const [label, matcher] of rule.buckets) {
        if (matcher.test(alias)) return label;
    }
    return "";
}

const capacityRouteReplacements = new Map();
const capacityPromptIds = new Set();
const capacityBucketLabels = new Set();
let capacitySplitLeafCount = 0;
let capacitySplitCanonicalPromptCount = 0;
let capacitySemanticAssignmentCount = 0;
for (const group of capacityGroups.values()) {
    const canonicalValues = [...group.canonicalEntries.keys()].sort();
    if (canonicalValues.length <= LEAF_SOFT_LIMIT) continue;

    capacitySplitLeafCount += 1;
    capacitySplitCanonicalPromptCount += canonicalValues.length;
    for (const canonical of canonicalValues) {
        for (const entry of group.canonicalEntries.get(canonical)) {
            const bucketLabel = capacitySemanticBucket(group, entry.prompt);
            if (!bucketLabel) continue;
            const semanticRoute = generatedRoute(
                group.kind,
                ...group.levels,
                bucketLabel,
            );
            if (!capacityRouteReplacements.has(entry.promptId)) {
                capacityRouteReplacements.set(entry.promptId, new Map());
            }
            capacityRouteReplacements
                .get(entry.promptId)
                .set(entry.routeName, semanticRoute);
            capacityPromptIds.add(entry.promptId);
            capacityBucketLabels.add(bucketLabel);
            capacitySemanticAssignmentCount += 1;
        }
    }
}

for (const [promptId, replacements] of capacityRouteReplacements) {
    const assignment = effectiveAssignments.get(promptId);
    const rewrittenRoutes = [
        ...new Set(
            assignment.routes.map(
                routeName => replacements.get(routeName) || routeName,
            ),
        ),
    ];
    promptRoutes[promptId] = rewrittenRoutes;
    promptHashes[promptId] = semanticHash(assignment.prompt);
    promptRouteCategories[promptId] = assignment.category_id;
}

const finalLeafCanonicalPrompts = new Map();
const assignmentChecksumRows = [];
for (const [promptId, assignment] of effectiveAssignments) {
    const canonical = canonicalPrompt(assignment.prompt) || `__prompt_id__${promptId}`;
    const replacements = capacityRouteReplacements.get(promptId);
    const finalTargets = [];
    for (const baseRouteName of assignment.routes) {
        const routeName = replacements?.get(baseRouteName) || baseRouteName;
        const resolved = resolvedRouteWithSourceLineage(
            routeName,
            assignment.category_name,
        );
        const target = [resolved.kind, ...resolved.levels];
        const key = JSON.stringify(target);
        if (!finalLeafCanonicalPrompts.has(key)) {
            finalLeafCanonicalPrompts.set(key, new Set());
        }
        finalLeafCanonicalPrompts.get(key).add(canonical);
        finalTargets.push(target);
    }
    assignmentChecksumRows.push(
        JSON.stringify([
            promptId,
            assignment.category_id,
            [...new Set(finalTargets.map(target => JSON.stringify(target)))]
                .sort(),
        ]),
    );
}

const leafCounts = [...finalLeafCanonicalPrompts.entries()]
    .map(([targetJson, canonicalValues]) => {
        const [kind, ...pathParts] = JSON.parse(targetJson);
        return {
            kind,
            path: pathParts,
            count: canonicalValues.size,
        };
    })
    .sort((a, b) => (
        a.kind.localeCompare(b.kind)
        || a.path.join("\u001f").localeCompare(b.path.join("\u001f"), "zh-CN")
    ));
const leafMaxPromptCount = Math.max(0, ...leafCounts.map(entry => entry.count));
const leafOverSoftLimit = leafCounts.filter(
    entry => entry.count > LEAF_SOFT_LIMIT,
);
const leafOverHardLimit = leafCounts.filter(
    entry => entry.count > LEAF_HARD_LIMIT,
);
if (leafOverSoftLimit.length || leafOverHardLimit.length) {
    throw new Error(
        `WeiLin leaf capacity exceeded: soft=${leafOverSoftLimit.length}, `
        + `hard=${leafOverHardLimit.length}, max=${leafMaxPromptCount}`,
    );
}

const renderedLeafCanonicalPrompts = new Map();
for (const [promptId, assignment] of effectiveAssignments) {
    const canonical = canonicalPrompt(assignment.prompt) || `__prompt_id__${promptId}`;
    const replacements = capacityRouteReplacements.get(promptId);
    const sourceDirectoryLevels = sourceCodexDirectoryLevels(
        assignment.category_name,
    );
    for (const baseRouteName of assignment.routes) {
        const routeName = replacements?.get(baseRouteName) || baseRouteName;
        const target = routes[routeName];
        if (!Array.isArray(target) || target.length < 2) {
            throw new Error(`Missing rendered route target ${routeName}`);
        }
        const [kind] = target;
        const levels = sourceDirectoryLevels.length
            ? sourceDirectoryLevels
            : resolvedRouteWithSourceLineage(
                routeName,
                assignment.category_name,
            ).levels;
        const key = JSON.stringify([kind, ...levels]);
        if (!renderedLeafCanonicalPrompts.has(key)) {
            renderedLeafCanonicalPrompts.set(key, new Set());
        }
        renderedLeafCanonicalPrompts.get(key).add(canonical);
    }
}
const renderedLeafCounts = [...renderedLeafCanonicalPrompts.entries()]
    .map(([targetJson, canonicalValues]) => {
        const [kind, ...pathParts] = JSON.parse(targetJson);
        return {
            kind,
            path: pathParts,
            count: canonicalValues.size,
        };
    })
    .sort((a, b) => (
        a.kind.localeCompare(b.kind)
        || a.path.join("\u001f").localeCompare(b.path.join("\u001f"), "zh-CN")
    ));
const renderedLeafMaxPromptCount = Math.max(
    0,
    ...renderedLeafCounts.map(entry => entry.count),
);
const renderedLeafOverSoftLimit = renderedLeafCounts.filter(
    entry => entry.count > LEAF_SOFT_LIMIT,
);
const renderedLeafOverHardLimit = renderedLeafCounts.filter(
    entry => entry.count > LEAF_HARD_LIMIT,
);
const sourceDirectoryCategoryCount = categories.filter(
    category => sourceCodexDirectoryLevels(category?.name).length > 0,
).length;

const nonQuarantinedPromptCount = (
    promptCount - Object.keys(quarantinedPrompts).length
);
if (effectiveAssignments.size !== nonQuarantinedPromptCount) {
    throw new Error(
        `Resolved prompt coverage mismatch: ${effectiveAssignments.size} `
        + `!= ${nonQuarantinedPromptCount}`,
    );
}
assignmentChecksumRows.sort();
const assignmentSha256 = crypto
    .createHash("sha256")
    .update(`${assignmentChecksumRows.join("\n")}\n`, "utf8")
    .digest("hex");
const normalizedCategoryNames = new Set(categories.map(category => (
    String(category?.name || "")
        .normalize("NFKC")
        .replaceAll("／", "/")
        .replace(/\s+/g, "")
        .toLowerCase()
)));
const normalizedPrompts = new Map();
for (const category of categories) {
    for (const prompt of category?.prompts || []) {
        const normalized = String(prompt?.prompt || "")
            .toLowerCase()
            .replace(/\r?\n/g, " ")
            .replace(/\s+/g, " ")
            .replace(/\s*,\s*/g, ",")
            .replace(/^[\s,]+|[\s,]+$/g, "");
        normalizedPrompts.set(normalized, (normalizedPrompts.get(normalized) || 0) + 1);
    }
}
const duplicatePromptGroups = [...normalizedPrompts.values()].filter(count => count > 1);

const referencedImages = new Set();
let noImageCount = 0;
for (const category of categories) {
    for (const prompt of category?.prompts || []) {
        const image = path.basename(String(prompt?.image || "").replaceAll("\\", "/"));
        if (image) referencedImages.add(image);
        else noImageCount += 1;
    }
}
const previewFiles = fs.existsSync(previewDir)
    ? new Set(fs.readdirSync(previewDir, { withFileTypes: true })
        .filter(entry => entry.isFile())
        .map(entry => entry.name))
    : new Set();
const missingPreviewFiles = [...referencedImages].filter(name => !previewFiles.has(name)).sort();
const orphanPreviewFiles = [...previewFiles].filter(name => !referencedImages.has(name)).sort();

const isolatedIds = Object.keys(quarantinedPrompts).sort();
const isolatedIdsSha256 = crypto
    .createHash("sha256")
    .update(`${isolatedIds.join("\n")}\n`, "utf8")
    .digest("hex");
function promptIdChecksum(promptIds) {
    const sortedIds = [...promptIds].sort();
    return crypto
        .createHash("sha256")
        .update(`${sortedIds.join("\n")}\n`, "utf8")
        .digest("hex");
}

const manifest = {
    schema_version: 1,
    taxonomy_version: "2026-07-30.source-directory-v1",
    path_strategy: PATH_STRATEGY,
    source_sha256: sourceSha256,
    source_last_modified: String(source.last_modified || ""),
    prefix_contracts: {
        "Anima/角色": { kind: "character", path: ["用户角色分类"] },
        "Anima/场景": { kind: "background", path: ["用户场景分类"] },
        "Anima/背景": { kind: "background", path: ["用户场景分类"] },
        "Anima/动作": { kind: "pose", path: ["用户动作分类"] },
        "Anima/姿势": { kind: "pose", path: ["用户动作分类"] },
        "Anima/服装": { kind: "clothing", path: ["用户服装分类"] },
        "角色": { kind: "character", path: ["用户角色分类"] },
        "场景": { kind: "background", path: ["用户场景分类"] },
        "背景": { kind: "background", path: ["用户场景分类"] },
        "动作": { kind: "pose", path: ["用户动作分类"] },
        "姿势": { kind: "pose", path: ["用户动作分类"] },
        "服装": { kind: "clothing", path: ["用户服装分类"] },
    },
    routes,
    mappings,
    prompt_routes: promptRoutes,
    prompt_hashes: promptHashes,
    prompt_route_categories: promptRouteCategories,
    quarantined_prompts: quarantinedPrompts,
    audit: {
        source_category_count: categories.length,
        canonical_category_count: normalizedCategoryNames.size,
        duplicate_category_alias_count: categories.length - normalizedCategoryNames.size,
        source_prompt_count: promptCount,
        classified_prompt_count: effectiveAssignments.size,
        assignment_sha256: assignmentSha256,
        leaf_soft_limit: LEAF_SOFT_LIMIT,
        leaf_hard_limit: LEAF_HARD_LIMIT,
        leaf_route_count: leafCounts.length,
        leaf_max_prompt_count: leafMaxPromptCount,
        leaf_over_soft_limit_count: leafOverSoftLimit.length,
        leaf_over_hard_limit_count: leafOverHardLimit.length,
        capacity_split_leaf_count: capacitySplitLeafCount,
        capacity_split_canonical_prompt_count: (
            capacitySplitCanonicalPromptCount
        ),
        capacity_frozen_prompt_count: capacityPromptIds.size,
        capacity_semantic_assignment_count: capacitySemanticAssignmentCount,
        capacity_semantic_bucket_count: capacityBucketLabels.size,
        capacity_semantic_buckets: [...capacityBucketLabels].sort(
            (a, b) => a.localeCompare(b, "zh-CN"),
        ),
        leaf_counts: leafCounts,
        rendered_path_strategy: PATH_STRATEGY,
        source_directory_category_count: sourceDirectoryCategoryCount,
        rendered_leaf_capacity_enforced: false,
        rendered_leaf_route_count: renderedLeafCounts.length,
        rendered_leaf_max_prompt_count: renderedLeafMaxPromptCount,
        rendered_leaf_over_soft_limit_count: renderedLeafOverSoftLimit.length,
        rendered_leaf_over_hard_limit_count: renderedLeafOverHardLimit.length,
        rendered_leaf_counts: renderedLeafCounts,
        mixed_category_count: mixedCategoryIds.size,
        mixed_prompt_route_count: mixedPromptCount,
        companion_prompt_route_count: companionPromptCount,
        companion_prompt_ids_sha256: promptIdChecksum(companionPromptIds),
        companion_prompt_kind_counts: Object.fromEntries(
            Object.entries(companionPromptIdsByKind)
                .map(([kind, ids]) => [kind, ids.size]),
        ),
        companion_prompt_kind_sha256: Object.fromEntries(
            Object.entries(companionPromptIdsByKind)
                .map(([kind, ids]) => [kind, promptIdChecksum(ids)]),
        ),
        supplemental_clothing_prompt_count: supplementalClothingPromptIds.size,
        supplemental_clothing_prompt_ids: [
            ...supplementalClothingPromptIds,
        ].sort(),
        supplemental_clothing_prompt_ids_sha256: promptIdChecksum(
            supplementalClothingPromptIds,
        ),
        supplemental_pose_prompt_count: supplementalPosePromptIds.size,
        supplemental_pose_prompt_ids: [
            ...supplementalPosePromptIds,
        ].sort(),
        supplemental_pose_prompt_ids_sha256: promptIdChecksum(
            supplementalPosePromptIds,
        ),
        supplemental_pose_phase2_prompt_count: (
            supplementalPosePhase2PromptIds.size
        ),
        supplemental_pose_phase2_prompt_ids: [
            ...supplementalPosePhase2PromptIds,
        ].sort(),
        supplemental_pose_phase2_prompt_ids_sha256: promptIdChecksum(
            supplementalPosePhase2PromptIds,
        ),
        supplemental_background_prompt_count: (
            supplementalBackgroundPromptIds.size
        ),
        supplemental_background_prompt_ids: [
            ...supplementalBackgroundPromptIds,
        ].sort(),
        supplemental_background_prompt_ids_sha256: promptIdChecksum(
            supplementalBackgroundPromptIds,
        ),
        supplemental_character_prompt_count: (
            supplementalCharacterPromptIds.size
        ),
        supplemental_character_prompt_ids: [
            ...supplementalCharacterPromptIds,
        ].sort(),
        supplemental_character_prompt_ids_sha256: promptIdChecksum(
            supplementalCharacterPromptIds,
        ),
        prompt_route_count: Object.keys(promptRoutes).length,
        targeted_prompt_count: targetedPromptCount,
        quarantined_category_count: isolatedCategoryIds.size,
        quarantined_prompt_count: isolatedIds.length,
        quarantined_prompt_ids_sha256: isolatedIdsSha256,
        canonical_prompt_count: normalizedPrompts.size,
        duplicate_prompt_group_count: duplicatePromptGroups.length,
        duplicate_prompt_extra_count: duplicatePromptGroups.reduce((total, count) => total + count - 1, 0),
        referenced_image_count: referencedImages.size,
        no_image_count: noImageCount,
        preview_file_count: previewFiles.size,
        missing_preview_file_count: missingPreviewFiles.length,
        missing_preview_files: missingPreviewFiles,
        orphan_preview_file_count: orphanPreviewFiles.length,
        orphan_preview_files: orphanPreviewFiles,
    },
};

const serializedManifest = `${JSON.stringify(manifest, null, 2)}\n`;
if (checkOnly) {
    const existing = fs.readFileSync(outputPath, "utf8");
    if (existing !== serializedManifest) {
        throw new Error("WeiLin taxonomy manifest is out of date");
    }
} else {
    fs.mkdirSync(path.dirname(outputPath), { recursive: true });
    fs.writeFileSync(outputPath, serializedManifest, "utf8");
}
console.log(JSON.stringify({
    outputPath,
    checkOnly,
    sourceSha256,
    categories: categories.length,
    prompts: promptCount,
    mappings: Object.keys(mappings).length,
    routes: Object.keys(routes).length,
    frozenPromptRoutes: Object.keys(promptRoutes).length,
    quarantinedPrompts: isolatedIds.length,
    isolatedIdsSha256,
    audit: Object.fromEntries(
        Object.entries(manifest.audit)
            .filter(([key]) => (
                !key.endsWith("_prompt_ids")
                && key !== "leaf_counts"
                && key !== "rendered_leaf_counts"
            )),
    ),
}, null, 2));
