@tool
extends EditorScript

const SOURCE_DIRECTORY := "res://assets/generated"


func _run() -> void:
	var source := DirAccess.open(SOURCE_DIRECTORY)
	if source == null:
		push_error("请把资源包解压到 res://assets/generated/<资产编号>/")
		return
	var builder := load("res://godot/AssetStudioSceneBuilder.gd")
	for folder_name in source.get_directories():
		var folder := SOURCE_DIRECTORY.path_join(folder_name)
		if not FileAccess.file_exists(folder.path_join("manifest.json")):
			continue
		if not FileAccess.file_exists(folder.path_join("model.glb")):
			continue
		var destination: String = builder.generate(folder)
		print("AGY 游戏资产已导入：", destination)
