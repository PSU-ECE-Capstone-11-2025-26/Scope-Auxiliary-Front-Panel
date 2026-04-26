using AFP.Components;
using Godot;

namespace AFP.View;

public partial class Macros : CenterContainer
{
	[Export] private PackedScene _macroControlScene;
	[Export] public uint NumberOfMacros { get; set; } = 4;
	private MacroControl[] _controls;
	public override void _Ready()
	{
		_controls = new MacroControl[NumberOfMacros];
		var container = GetNode<HBoxContainer>("MacroContainer");
		for (ushort i = 0; i < NumberOfMacros; i++)
		{
			var macro = _macroControlScene.Instantiate<MacroControl>();
			macro.Slot = i;
			_controls[i] = macro;
			container.AddChild(macro);
		}
	}

	public MacroControl GetMacro(ushort slot)
	{
		return _controls[slot];
	}
}
