$ErrorActionPreference = "Stop"

$source = "G:\ComfyUI-aki-v3\benchmark_reports\2026-08-24_anima_anima38_krea2\raw\manual_scores.json"
$destination = "G:\ComfyUI-aki-v3\benchmark_reports\2026-08-24_anima_anima29_krea2\raw\manual_scores.json"
$payload = [IO.File]::ReadAllText($source) | ConvertFrom-Json

$payload.review_method = "Full-resolution side-by-side human review. Original Anima and Krea2 scores are reused from the same-day baseline; Anima 2.9B was newly reviewed. Automatic image metrics were not used as an aesthetic score."
$payload.model_labels.psobject.Properties.Remove("anima_38b")
$payload.model_labels | Add-Member -NotePropertyName "anima_29b" -NotePropertyValue "Anima 2.9B preview v1 BF16"

$scores = @{
    smoke_single_character = @(4.1, 4.4, 4.2, "单一怀表、制服和车站成立，双手较自然；仍是大半身而非完整全身。")
    anime_action = @(4.2, 4.5, 4.0, "红发、白外套、弯刀、机械乌鸦和屋顶动势齐全；飞跃方向与肢体关系略夸张。")
    architecture_perspective = @(3.1, 4.2, 4.2, "中央水池、圆形天窗和深空间成立，但楼层数偏多且只给出中央单楼梯。")
    attribute_swap = @(4.9, 4.3, 4.6, "左右发色、外套和反色雨伞全部正确，黄猫位于单一绿箱上，基准种子无多余物件。")
    counting_still_life = @(3.2, 3.8, 4.0, "三枚绿色水果、钥匙和红本正确，但杯子由两个变成三个，总数为八；画面还有明显白边。")
    dance_foreshortening = @(3.6, 4.3, 3.8, "近景大手和空中动势强，但深劈叉不清楚，一条腿被布料和机位弱化。")
    english_signage = @(3.2, 4.4, 4.3, "MOONLIGHT CAFE 清楚、红自行车和无人街道正确；24H 很小，三行菜单基本缺失。")
    low_light_neon = @(4.9, 4.7, 4.6, "黄衣骑手、蓝包裹、红左青右及对应湿地反射全部清楚，没有人群。")
    photoreal_carpenter = @(3.3, 4.4, 4.2, "老人、护目镜、围裙和木工作坊成立，照片感良好；工具更像金属尺而非木工刨，也不是全身。")
    product_design = @(2.9, 4.2, 4.2, "单表、蓝表带和右侧红表冠正确，但表盘为圆形且不透明，指针结构也超过严格两针。")
    risograph_poster = @(3.2, 4.2, 4.4, "双色网点、宇航员、向日葵和留白成立；没有浇水动作，标题误成 CROW/GROW 的近似字。")
    three_character_binding = @(4.7, 4.4, 4.3, "三人左右和跪姿、怀表、透明伞、黄猫蓝箱、红车及 PLATFORM 9 基本完整，左侧制服锚点略弱。")
    two_person_action = @(2.4, 4.3, 3.8, "双人、茶流和橙猫可读，但把动作改成陶壶倒入中央玻璃壶，猫也在桌面而非桌下。")
    natural_landscape = @(4.2, 4.6, 4.7, "S 形蓝河、黑山、左黄苔右玄武岩和无人建筑约束成立；白鸟数量明显超过五。")
    chinese_bookshop_sign = @(2.6, 4.3, 4.4, "传统店面、双灯笼、中央绿衣顾客和湿地氛围正确，但两块中文招牌均为伪字。")
    tag_style_character = @(4.9, 4.6, 4.6, "银色短发、琥珀眼、军装、白手套、黑靴、怀表、雾中站台和全身构图全部稳定。")
    unusual_viewpoint = @(3.7, 4.2, 3.9, "箱内仰视、温室和放大镜成立；蝴蝶落在上方手指而非玻璃边，指向关系发生替换。")
    length_short = @(4.4, 4.3, 4.1, "三人、雨伞、黄猫、蓝箱和红车齐全；箱体横向拉长，角色服装身份较简化。")
    length_medium = @(4.7, 4.6, 4.4, "三人站位、PLATFORM 9、怀表、透明伞、猫箱、红车和雨夜反射均保持。")
    length_long = @(2.7, 4.5, 4.3, "没有花图且站台画面连贯，但三人缩减为两人，文字、时间、钟和大量后半段细节被省略。")
    aspect_ultrawide = @(4.8, 4.6, 4.6, "超宽构图中的两人、横向红车、海面、道口和右侧灯塔关系清楚。")
    aspect_ultratall = @(4.6, 4.4, 4.5, "单人、重复平台、纵深和顶部圆形出口稳定；向上光束不如原版明确。")
    aspect_square = @(4.7, 3.8, 4.5, "中央喷泉、左右恰好两树和单一园丁正确，但主体缩在大面积白边中央，成品观感受损。")
}

foreach ($caseProperty in $payload.cases.psobject.Properties) {
    $caseId = $caseProperty.Name
    if (-not $scores.ContainsKey($caseId)) {
        throw "Missing Anima 2.9B score for $caseId"
    }
    $case = $caseProperty.Value
    $case.psobject.Properties.Remove("anima_38b")
    $row = $scores[$caseId]
    $case | Add-Member -NotePropertyName "anima_29b" -NotePropertyValue ([pscustomobject]@{
        prompt_adherence = $row[0]
        visual_quality = $row[1]
        structure_artifacts = $row[2]
        note = $row[3]
    })
}

$reliabilityNotes = @{
    attribute_swap = "核心颜色和左右绑定 3/3；严格无额外物件约 2/3，一轮增加红色行李箱。"
    dance_foreshortening = "三轮都有单人空中动作，但近景大手与可信深劈叉同时满足约 1/3。"
    three_character_binding = "主要人物身份和站位约 3/3 可读；恰好三人约 2/3，一轮多出小人物。"
}
foreach ($property in $payload.reliability.psobject.Properties) {
    $property.Value.psobject.Properties.Remove("anima_38b")
    $property.Value | Add-Member -NotePropertyName "anima_29b" -NotePropertyValue $reliabilityNotes[$property.Name]
}

$json = $payload | ConvertTo-Json -Depth 20
[IO.File]::WriteAllText($destination, $json, [Text.UTF8Encoding]::new($false))
"Wrote $destination"
