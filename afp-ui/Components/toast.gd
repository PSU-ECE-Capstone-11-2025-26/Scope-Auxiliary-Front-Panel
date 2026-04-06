extends Control

@onready var timer: Timer = $Timer
@onready var label: RichTextLabel = $Panel/VBoxContainer/ToastMessageLabel
@onready var header: Label = $Panel/VBoxContainer/Header

@export var flash_count: int = 3

var _queue: Array[ToastMessage] = []
var _header_count: int = 0

# for easier use from C#
func add_message_compat(type: int, msg: String) -> void:
	add_message(ToastMessage.new(type, msg))
	

func add_message(msg: ToastMessage) -> void:
	_queue.push_back(msg)
	_header_count += 1
	_update_header(_header_count)
	if !visible:
		show()


func _on_timer_timeout() -> void:
	if _queue.is_empty():
		hide()
	else:
		_header_count -= 1
		_update_header(_header_count)
		show_next_message()


func _on_visibility_changed() -> void:
	if visible:
		show_next_message()
		timer.start()


func show_next_message() -> void:
	var msg: ToastMessage = _queue.pop_front()
	label.clear()
	label.append_text("\t")
	label.add_image(msg.get_icon())
	label.append_text("\t\t")
	label.push_color(msg.get_color())
	label.append_text(msg.text)
	label.pop()
	$Panel.self_modulate = msg.get_color()
	await get_tree().create_timer(1.0).timeout
	$Panel.self_modulate = Color.WHITE

func _update_header(count: int) -> void:
	header.text = "%d message(s)" % count
