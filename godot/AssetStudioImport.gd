@tool
extends EditorScript

const SOURCE_DIRECTORY := "res://assets/generated"


func _run() -> void:
	var source := DirAccess.open(SOURCE_DIRECTORY)
	if source == null:
		push_error("请把资源包解压到 res://assets/generated/<资产编号>/")
		return
	for folder_name in source.get_directories():
		var folder := SOURCE_DIRECTORY.path_join(folder_name)
		var metadata_path := folder.path_join("manifest.json")
		var glb_path := folder.path_join("model.glb")
		if not FileAccess.file_exists(metadata_path) or not FileAccess.file_exists(glb_path):
			continue
		var metadata := JSON.parse_string(FileAccess.get_file_as_string(metadata_path))
		if not metadata is Dictionary:
			push_error("资产文件解析失败：" + folder)
			continue
		var imported := load(glb_path) as PackedScene
		if imported == null:
			push_error("GLB 导入失败：" + glb_path)
			continue
		var category := str(metadata.get("type", "prop"))
		var character := category == "character" or category == "monster"
		var root: CollisionObject3D
		if character:
			root = CharacterBody3D.new()
		else:
			root = StaticBody3D.new()
		root.name = str(metadata.get("title", folder_name))
		var visual := imported.instantiate()
		root.add_child(visual)
		visual.owner = root

		var quality := metadata.get("quality", {})
		var bounds := quality.get("bounds", [])
		if bounds.size() == 2:
			var minimum := bounds[0]
			var maximum := bounds[1]
			var size := Vector3(float(maximum[0] - minimum[0]), float(maximum[1] - minimum[1]), float(maximum[2] - minimum[2]))
			var center := Vector3(float(maximum[0] + minimum[0]) / 2.0, float(maximum[1] + minimum[1]) / 2.0, float(maximum[2] + minimum[2]) / 2.0)
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
		if packed.pack(root) != OK:
			push_error("Godot 场景打包失败：" + folder)
			root.free()
			continue
		var destination := folder.path_join("game_asset.tscn")
		if ResourceSaver.save(packed, destination) != OK:
			push_error("Godot 场景保存失败：" + destination)
		else:
			print("AGY 游戏资产已导入：", destination)
		root.free()

