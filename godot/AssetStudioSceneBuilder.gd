@tool
extends RefCounted


static func generate(folder: String) -> String:
	var manifest_path := folder.path_join("manifest.json")
	var model_path := folder.path_join("model.glb")
	assert(FileAccess.file_exists(manifest_path), "资产缺少 manifest.json")
	assert(FileAccess.file_exists(model_path), "资产缺少 model.glb")

	var metadata = JSON.parse_string(FileAccess.get_file_as_string(manifest_path))
	assert(metadata is Dictionary, "资产清单格式错误")
	var imported := load(model_path) as PackedScene
	assert(imported != null, "Godot 无法读取 GLB")

	var category := str(metadata.get("type", "prop"))
	var character := category == "character" or category == "monster"
	var root: CollisionObject3D
	if character:
		root = CharacterBody3D.new()
	else:
		root = StaticBody3D.new()
	root.name = str(metadata.get("title", folder.get_file()))

	var visual := imported.instantiate()
	root.add_child(visual)
	visual.owner = root

	var quality: Dictionary = metadata.get("quality", {})
	var bounds: Array = quality.get("bounds", [])
	assert(bounds.size() == 2, "资产缺少模型空间边界")
	var minimum: Array = bounds[0]
	var maximum: Array = bounds[1]
	assert(minimum.size() == 3 and maximum.size() == 3, "空间边界格式错误")
	var size := Vector3(
		float(maximum[0]) - float(minimum[0]),
		float(maximum[1]) - float(minimum[1]),
		float(maximum[2]) - float(minimum[2])
	)
	var center := Vector3(
		(float(maximum[0]) + float(minimum[0])) / 2.0,
		(float(maximum[1]) + float(minimum[1])) / 2.0,
		(float(maximum[2]) + float(minimum[2])) / 2.0
	)
	var collider := CollisionShape3D.new()
	if character:
		var capsule := CapsuleShape3D.new()
		capsule.radius = max(0.05, max(size.x, size.z) * 0.4)
		capsule.height = max(size.y, capsule.radius * 2.0)
		collider.shape = capsule
	else:
		var box := BoxShape3D.new()
		box.size = size.max(Vector3(0.01, 0.01, 0.01))
		collider.shape = box
	collider.position = center
	root.add_child(collider)
	collider.owner = root

	var packed := PackedScene.new()
	assert(packed.pack(root) == OK, "Godot 场景打包失败")
	var destination := folder.path_join("game_asset.tscn")
	assert(ResourceSaver.save(packed, destination) == OK, "Godot 场景保存失败")
	root.free()
	return destination
