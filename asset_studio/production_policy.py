from dataclasses import dataclass


VIEW_ORDER = ("front", "right", "back", "left")


@dataclass(frozen=True)
class AssetProductionPolicy:
    kind: str
    complexity: str
    require_multiview: bool
    required_views: tuple[str, ...]
    reason: str
    modular: bool


def resolve_production_policy(kind: str, complexity: str = "standard") -> AssetProductionPolicy:
    if kind not in {"character", "monster", "equipment", "weapon", "prop", "scene"}:
        raise ValueError("未知的游戏资产类别")
    if complexity not in {"standard", "complex"}:
        raise ValueError("资产复杂程度无效")

    animated = kind in {"character", "monster"}
    wearable = kind == "equipment"
    detailed_object = kind in {"weapon", "prop"} and complexity == "complex"
    require_multiview = animated or wearable or detailed_object
    descriptions = {
        "character": "可动人物必须完成同一人物的四视图、服饰层次及骨骼动作验收",
        "monster": "怪物必须明确四肢、关节、外部附属结构和四个视角",
        "equipment": "可穿戴装备需要检查正背与左右厚度以及装配位置",
        "weapon": "普通独立武器允许单图；机关武器和复杂外形使用四视图",
        "prop": "结构简单的独立道具允许单图；复杂装配件使用四视图",
        "scene": "场景按可独立使用的门墙屋檐、道路与植被模块制作；模块可使用单图",
    }
    return AssetProductionPolicy(
        kind=kind,
        complexity=complexity,
        require_multiview=require_multiview,
        required_views=VIEW_ORDER if require_multiview else ("front",),
        reason=descriptions[kind],
        modular=kind == "scene",
    )


def validate_production_submission(
    *,
    kind: str,
    complexity: str,
    quality_target: str,
    view_source: str,
    mode: str,
    multi_views: bool,
    multi_view_strategy: str,
    supplied_views: set[str],
    has_front: bool,
    has_prompt: bool,
    scene_module: str,
) -> AssetProductionPolicy:
    policy = resolve_production_policy(kind, complexity)
    if quality_target not in {"prototype", "production"}:
        raise ValueError("游戏资产制作类型无效")
    if view_source not in {"qimage", "uploaded"}:
        raise ValueError("参考图来源无效")
    if quality_target == "prototype":
        return policy
    if mode != "whole":
        raise ValueError("赛季正式候选采用 Pixal3D 完整模型推理，分件实验请使用概念实验模式")
    if kind == "scene" and not scene_module.strip():
        raise ValueError("赛季场景请指定独立建筑或地形模块名称，分别制作完整模块")
    if policy.require_multiview:
        if not multi_views or multi_view_strategy != "four":
            raise ValueError(f"{kind} 正式资产必须使用正面、右面、背面、左面四视图")
        if view_source == "uploaded":
            if not has_front or supplied_views != {"right", "back", "left"}:
                raise ValueError("上传多视图需要同一资产的正面、右面、背面、左面四张实际参考图")
        elif supplied_views:
            raise ValueError("QImage 自动生成多视图使用同一正面母版；上传四视图请切换为外部多视图")
        elif not has_front and not has_prompt:
            raise ValueError("QImage 自动生成角色时必须提供造型描述或正面参考原画")
    else:
        if view_source == "uploaded" and not has_front:
            raise ValueError("使用外部图片制作独立道具或建筑模块时，必须上传主体原画")
        if multi_views and multi_view_strategy != "four":
            raise ValueError("使用多视图时请选择正面、右面、背面、左面四视图")
        if supplied_views and (not multi_views or supplied_views != {"right", "back", "left"} or not has_front):
            raise ValueError("自行提供侧面参考时，需要提交完整四视图")
        if not has_front and not has_prompt:
            raise ValueError("制作独立场景模块或道具需要提供正面图片或造型描述")
    return policy
