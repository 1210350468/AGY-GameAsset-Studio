from asset_studio.nextgen import (
    ANIMA_MODEL,
    QWEN_MODEL,
    anima_candidates_workflow,
    qwen_character_view_workflow,
)


def test_anima_candidate_batch_is_a_real_connected_comfy_graph():
    workflow = anima_candidates_workflow(
        "original dark fantasy armored warrior, full body, neutral pose",
        seed=20261118,
        count=4,
    )
    assert workflow["1"]["inputs"]["unet_name"] == ANIMA_MODEL
    assert workflow["6"]["inputs"]["batch_size"] == 4
    assert workflow["7"]["inputs"]["positive"] == ["4", 0]
    assert workflow["7"]["inputs"]["negative"] == ["5", 0]
    assert workflow["9"]["inputs"]["images"] == ["8", 0]


def test_qwen_reference_connects_using_comfy_autogrow_dotted_key():
    workflow = qwen_character_view_workflow(
        "<image1> full body back view of the same character",
        "anima_selected_character.png",
        seed=20261118,
    )
    assert workflow["1"]["inputs"]["unet_name"] == QWEN_MODEL
    assert workflow["5"]["inputs"]["images.image_1"] == ["4", 0]
    assert "images" not in workflow["5"]["inputs"]
    assert workflow["5"]["inputs"]["prompt"].startswith("<image1>")
    assert workflow["6"]["inputs"]["latent_image"] == ["5", 2]
    assert workflow["8"]["inputs"]["images"] == ["7", 0]
