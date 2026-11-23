extends Control

const UI_CONFIG := {
	"base_padding": 16,
	"corner_radius": 12,
	"border_width": 2,
	"tap_button_min_size": Vector2(260, 120),
	"debug_button_min_size": Vector2(120, 52),
	"title_font_size": 28,
	"tap_font_size": 28,
	"debug_btn_font_size": 20,
	"debug_text_font_size": 18,
	"max_log_entries": 12,
	"debug_panel_min_height": 280,
}

const COLORS := {
	"background": Color(0.12, 0.13, 0.16, 1.0),
	"surface": Color(0.20, 0.22, 0.27, 1.0),
	"surface_pressed": Color(0.28, 0.31, 0.38, 1.0),
	"accent": Color(0.25, 0.56, 0.96, 1.0),
	"accent_pressed": Color(0.18, 0.44, 0.80, 1.0),
	"border": Color(0.38, 0.42, 0.50, 1.0),
	"debug_bg": Color(0.07, 0.08, 0.10, 0.92),
	"text_primary": Color(0.95, 0.96, 0.98, 1.0),
	"text_muted": Color(0.72, 0.76, 0.84, 1.0),
}

const TEXTS := {
	"title": "ATLAS Prototype",
	"tap_prefix": "TAP COUNTER\n",
	"debug_button": "Debug",
	"debug_header": "=== DEBUG OVERLAY ===",
}

var _tap_count: int = 0
var _debug_visible: bool = false
var _log_entries: Array[String] = []

var _safe_margin_container: MarginContainer
var _tap_button: Button
var _debug_button: Button
var _debug_panel: PanelContainer
var _debug_label: RichTextLabel


func _ready() -> void:
	_build_ui()
	_apply_safe_area_margins()
	get_viewport().size_changed.connect(_on_viewport_size_changed)
	_append_log("App started (Godot %s)" % Engine.get_version_info().get("string", "4.4.1"))
	_update_tap_button_text()
	_refresh_debug_overlay()


func _process(_delta: float) -> void:
	if _debug_visible:
		_refresh_debug_overlay()


func _build_ui() -> void:
	var bg := ColorRect.new()
	bg.color = COLORS["background"]
	bg.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(bg)

	_safe_margin_container = MarginContainer.new()
	_safe_margin_container.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(_safe_margin_container)

	var root_vbox := VBoxContainer.new()
	root_vbox.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	root_vbox.size_flags_vertical = Control.SIZE_EXPAND_FILL
	root_vbox.add_theme_constant_override("separation", UI_CONFIG["base_padding"])
	_safe_margin_container.add_child(root_vbox)

	# Top bar with title and Debug toggle button
	var top_bar := HBoxContainer.new()
	top_bar.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	root_vbox.add_child(top_bar)

	var title_label := Label.new()
	title_label.text = TEXTS["title"]
	title_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	title_label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	title_label.add_theme_font_size_override("font_size", UI_CONFIG["title_font_size"])
	title_label.add_theme_color_override("font_color", COLORS["text_primary"])
	top_bar.add_child(title_label)

	_debug_button = _create_touch_button(
		TEXTS["debug_button"],
		UI_CONFIG["debug_button_min_size"],
		UI_CONFIG["debug_btn_font_size"],
		COLORS["surface"],
		COLORS["surface_pressed"]
	)
	_debug_button.pressed.connect(_on_debug_button_pressed)
	top_bar.add_child(_debug_button)

	# Debug overlay panel (hidden by default)
	_debug_panel = PanelContainer.new()
	_debug_panel.visible = false
	_debug_panel.custom_minimum_size = Vector2(0, UI_CONFIG["debug_panel_min_height"])
	_debug_panel.add_theme_stylebox_override("panel", _make_box_style(COLORS["debug_bg"], COLORS["border"]))
	root_vbox.add_child(_debug_panel)

	var debug_margin := MarginContainer.new()
	var pad: int = UI_CONFIG["base_padding"]
	debug_margin.add_theme_constant_override("margin_left", pad)
	debug_margin.add_theme_constant_override("margin_right", pad)
	debug_margin.add_theme_constant_override("margin_top", pad)
	debug_margin.add_theme_constant_override("margin_bottom", pad)
	_debug_panel.add_child(debug_margin)

	_debug_label = RichTextLabel.new()
	_debug_label.bbcode_enabled = false
	_debug_label.scroll_following = true
	_debug_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_debug_label.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_debug_label.add_theme_font_size_override("normal_font_size", UI_CONFIG["debug_text_font_size"])
	_debug_label.add_theme_color_override("default_color", COLORS["text_muted"])
	debug_margin.add_child(_debug_label)

	# Center touch area
	var center_box := CenterContainer.new()
	center_box.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	center_box.size_flags_vertical = Control.SIZE_EXPAND_FILL
	root_vbox.add_child(center_box)

	_tap_button = _create_touch_button(
		"",
		UI_CONFIG["tap_button_min_size"],
		UI_CONFIG["tap_font_size"],
		COLORS["accent"],
		COLORS["accent_pressed"]
	)
	_tap_button.pressed.connect(_on_tap_button_pressed)
	center_box.add_child(_tap_button)


func _create_touch_button(
	label_text: String,
	min_size: Vector2,
	font_size: int,
	normal_color: Color,
	pressed_color: Color
) -> Button:
	var btn := Button.new()
	btn.text = label_text
	btn.custom_minimum_size = min_size
	btn.focus_mode = Control.FOCUS_NONE
	btn.add_theme_font_size_override("font_size", font_size)
	btn.add_theme_color_override("font_color", COLORS["text_primary"])
	btn.add_theme_color_override("font_pressed_color", COLORS["text_primary"])
	btn.add_theme_color_override("font_hover_color", COLORS["text_primary"])

	var normal_style := _make_box_style(normal_color, COLORS["border"])
	var pressed_style := _make_box_style(pressed_color, COLORS["text_primary"])
	btn.add_theme_stylebox_override("normal", normal_style)
	btn.add_theme_stylebox_override("hover", normal_style)
	btn.add_theme_stylebox_override("pressed", pressed_style)
	return btn


func _make_box_style(bg_color: Color, border_color: Color) -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = bg_color
	style.border_color = border_color
	var bw: int = UI_CONFIG["border_width"]
	style.border_width_left = bw
	style.border_width_right = bw
	style.border_width_top = bw
	style.border_width_bottom = bw
	var cr: int = UI_CONFIG["corner_radius"]
	style.corner_radius_top_left = cr
	style.corner_radius_top_right = cr
	style.corner_radius_bottom_left = cr
	style.corner_radius_bottom_right = cr
	return style


func _get_safe_area_margins() -> Dictionary:
	var safe_area: Rect2i = DisplayServer.get_display_safe_area()
	var window_size: Vector2i = DisplayServer.window_get_size()
	var viewport_size: Vector2 = get_viewport_rect().size

	var scale_x: float = 1.0
	var scale_y: float = 1.0
	if window_size.x > 0 and window_size.y > 0 and viewport_size.x > 0.0 and viewport_size.y > 0.0:
		scale_x = viewport_size.x / float(window_size.x)
		scale_y = viewport_size.y / float(window_size.y)

	var left: int = maxi(0, int(round(float(safe_area.position.x) * scale_x)))
	var top: int = maxi(0, int(round(float(safe_area.position.y) * scale_y)))
	var right: int = maxi(0, int(round(float(window_size.x - safe_area.end.x) * scale_x)))
	var bottom: int = maxi(0, int(round(float(window_size.y - safe_area.end.y) * scale_y)))

	var base_pad: int = UI_CONFIG["base_padding"]
	return {
		"left": left + base_pad,
		"top": top + base_pad,
		"right": right + base_pad,
		"bottom": bottom + base_pad,
	}


func _apply_safe_area_margins() -> void:
	var margins: Dictionary = _get_safe_area_margins()
	_safe_margin_container.add_theme_constant_override("margin_left", margins["left"])
	_safe_margin_container.add_theme_constant_override("margin_top", margins["top"])
	_safe_margin_container.add_theme_constant_override("margin_right", margins["right"])
	_safe_margin_container.add_theme_constant_override("margin_bottom", margins["bottom"])


func _on_viewport_size_changed() -> void:
	_apply_safe_area_margins()
	_append_log("Viewport resized: %s" % str(get_viewport_rect().size))
	if _debug_visible:
		_refresh_debug_overlay()


func _on_tap_button_pressed() -> void:
	_tap_count += 1
	_update_tap_button_text()
	_append_log("Tap #%d" % _tap_count)
	if _debug_visible:
		_refresh_debug_overlay()


func _on_debug_button_pressed() -> void:
	_debug_visible = not _debug_visible
	_debug_panel.visible = _debug_visible
	_append_log("Debug overlay: %s" % ("ON" if _debug_visible else "OFF"))
	if _debug_visible:
		_refresh_debug_overlay()


func _update_tap_button_text() -> void:
	_tap_button.text = "%s%d" % [TEXTS["tap_prefix"], _tap_count]


func _append_log(message: String) -> void:
	var timestamp: String = Time.get_time_string_from_system()
	_log_entries.append("[%s] %s" % [timestamp, message])
	var max_entries: int = UI_CONFIG["max_log_entries"]
	while _log_entries.size() > max_entries:
		_log_entries.remove_at(0)


func _refresh_debug_overlay() -> void:
	var fps: int = int(Engine.get_frames_per_second())
	var window_size: Vector2i = DisplayServer.window_get_size()
	var viewport_size: Vector2 = get_viewport_rect().size
	var safe_area: Rect2i = DisplayServer.get_display_safe_area()
	var margins: Dictionary = _get_safe_area_margins()

	var lines: Array[String] = [
		TEXTS["debug_header"],
		"FPS: %d" % fps,
		"Window: %dx%d | Viewport: %dx%d" % [
			window_size.x, window_size.y,
			int(viewport_size.x), int(viewport_size.y),
		],
		"SafeArea: %s" % str(safe_area),
		"Margins (L/T/R/B): %d / %d / %d / %d" % [
			margins["left"], margins["top"], margins["right"], margins["bottom"]
		],
		"",
		"--- Log ---",
	]
	lines.append_array(_log_entries)
	_debug_label.text = "\n".join(lines)
