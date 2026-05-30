using Godot;

namespace AFP.Components;

public partial class ScopeOption : HBoxContainer
{
	[Signal]
	public delegate void ScopeToggledEventHandler(bool enabled, string resourceName);

	public string ResourceName;
	private BaseButton.ToggledEventHandler _callback;
	public void Init(string resourceName, bool enabled, ButtonGroup group)
	{
		ResourceName = resourceName;
		GetNode<Label>("Label").Text = resourceName;
		var c = GetNode<CheckBox>("CheckBox");
		_callback = on => EmitSignal(SignalName.ScopeToggled, on, resourceName);
		c.Toggled += _callback;
		c.ButtonGroup = group;
		c.SetPressedNoSignal(enabled);
	}

	public override void _ExitTree()
	{
		GetNode<CheckBox>("CheckBox").Toggled -= _callback;
	}
}
