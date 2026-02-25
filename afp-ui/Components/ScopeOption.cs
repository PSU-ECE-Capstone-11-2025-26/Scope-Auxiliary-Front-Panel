using Godot;

namespace AFP.Components;

public partial class ScopeOption : HBoxContainer
{
	public void Init(string idn, bool enabled, ButtonGroup group)
	{
		GetNode<Label>("Label").Text = idn;
		var c = GetNode<CheckBox>("CheckBox");
		c.ButtonGroup = group;
		c.ButtonPressed = enabled;
	}
}
