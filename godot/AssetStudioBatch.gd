extends SceneTree


func _initialize() -> void:
	call_deferred("_generate")


func _generate() -> void:
	var arguments := OS.get_cmdline_user_args()
	if arguments.size() != 1:
		push_error("必须提供一个资产编号")
		quit(1)
		return
	var folder := "res://assets/generated".path_join(arguments[0])
	var builder := load("res://godot/AssetStudioSceneBuilder.gd")
	var destination: String = builder.generate(folder)
	var scene := load(destination) as PackedScene
	if scene == null:
		push_error("Godot 场景无法重新加载：" + destination)
		quit(1)
		return
	var instance := scene.instantiate()
	if instance.find_children("*", "CollisionShape3D", true, false).is_empty():
		push_error("Godot 场景缺少碰撞体：" + destination)
		instance.free()
		quit(1)
		return
	var manifest = JSON.parse_string(FileAccess.get_file_as_string(folder.path_join("manifest.json")))
	if bool(manifest.get("rig_generated", false)) and instance.find_children("*", "Skeleton3D", true, false).is_empty():
		push_error("Godot 场景缺少角色骨骼：" + destination)
		instance.free()
		quit(1)
		return
	instance.free()
	print("AGY Godot scene generated: ", destination)
	quit(0)
