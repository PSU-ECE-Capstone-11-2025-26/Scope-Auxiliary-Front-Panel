class_name ToastMessage
extends RefCounted

enum Type {
	INFO = 0,
	WARN = 1,
	ERROR = 2,
}

var _icons: Dictionary[Type, Texture2D] = {
	Type.INFO: preload("res://icons/Info.svg"),
	Type.WARN: preload("res://icons/Warning.svg"),
	Type.ERROR: preload("res://icons/Error.svg"),
}

var type: Type
var text: String

func _init(toast_type: Type, message: String) -> void:
	self.type = toast_type
	self.text = message


func get_icon() -> Texture2D:
	return _icons[type]


func get_color() -> Color:
	match type:
		Type.INFO:
			return Color.STEEL_BLUE
		Type.WARN:
			return Color.DARK_GOLDENROD
		Type.ERROR:
			return Color.FIREBRICK
		_:
			return Color.WHITE
