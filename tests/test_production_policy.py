from asset_studio.production_policy import resolve_production_policy, validate_production_submission


def test_people_and_monsters_use_orthogonal_views():
    for kind in ("character", "monster", "equipment"):
        policy = resolve_production_policy(kind)
        assert policy.require_multiview
        assert policy.required_views == ("front", "right", "back", "left")


def test_simple_props_and_modular_scenes_keep_single_image():
    for kind in ("weapon", "prop", "scene"):
        policy = resolve_production_policy(kind, "standard")
        assert policy.required_views == ("front",)
    for kind in ("weapon", "prop"):
        assert resolve_production_policy(kind, "complex").require_multiview


def test_qimage_design_can_generate_four_views_from_a_real_front_source():
    policy = validate_production_submission(
        kind="character", complexity="standard", quality_target="production",
        view_source="qimage", mode="whole", multi_views=True,
        multi_view_strategy="four", supplied_views=set(), has_front=True,
        has_prompt=False, scene_module="",
    )
    assert policy.require_multiview
    assert policy.required_views == ("front", "right", "back", "left")


def test_independent_stone_prop_is_valid_single_view():
    policy = validate_production_submission(
        kind="prop", complexity="standard", quality_target="production",
        view_source="qimage", mode="whole", multi_views=False,
        multi_view_strategy="four", supplied_views=set(), has_front=False,
        has_prompt=True, scene_module="",
    )
    assert not policy.require_multiview


def test_real_architecture_module_requires_identifiable_component():
    policy = validate_production_submission(
        kind="scene", complexity="standard", quality_target="production",
        view_source="qimage", mode="whole", multi_views=False,
        multi_view_strategy="four", supplied_views=set(), has_front=False,
        has_prompt=True, scene_module="临江州东门·二层青瓦屋顶",
    )
    assert policy.modular and policy.required_views == ("front",)
