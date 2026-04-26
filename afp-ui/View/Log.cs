using Godot;

namespace AFP.View;

public partial class Log : RichTextLabel
{
	public override void _Ready()
	{
		Global.Instance.OnLog += _onLogCall;
	}

	private void _onLogCall(short level, string message)
	{
		string strLvl = level switch
		{
			0 => "[color=STEELBLUE][lb]INFO[rb][/color] ",
			1 => "[color=DARK_GOLDENROD][lb]WARN[rb][/color] ",
			2 => "[color=FIREBRICK][lb]ERROR[rb][/color] ",
			3 => "[color=SEA_GREEN][lb]DEBUG[rb][/color] ",
			_ => ""
		};
		AppendText(strLvl + message + "\n");
	}
}
