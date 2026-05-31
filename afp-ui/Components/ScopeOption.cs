using Godot;

namespace AFP.Components;

public partial class ScopeOption : HBoxContainer
{
	[Signal]
	public delegate void ScopeToggledEventHandler(bool enabled, string resourceName);

	public string ResourceName;
	private CheckButton _button;
	private BaseButton.ToggledEventHandler _callback;

	public override void _Ready()
	{
		_button = GetNode<CheckButton>("%SelectButton");
	}
	public void Init(string resourceName, bool enabled)
	{
		ResourceName = resourceName;
		_button.Text = resourceName;
		_callback = on => EmitSignal(SignalName.ScopeToggled, on, resourceName);
		_button.Toggled += _callback;
		_button.SetPressedNoSignal(enabled);
	}

	public override void _ExitTree()
	{
		_button.Toggled -= _callback;
	}
}
