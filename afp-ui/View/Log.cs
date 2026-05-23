using AFP.Core;
using Godot;

namespace AFP.View;

public partial class Log : RichTextLabel
{
	private double _startupTime;
	public override void _Ready()
	{
		_startupTime = Time.GetUnixTimeFromSystem();
		Global.Logger.OnLog += _onLogCall;
	}

	private void _onLogCall(LogLevel level, string message)
	{
		string strLvl = level switch
		{
			LogLevel.Info => "[color=STEELBLUE][lb]INFO[rb][/color] ",
			LogLevel.Warning => "[color=DARK_GOLDENROD][lb]WARN[rb][/color] ",
			LogLevel.Error => "[color=FIREBRICK][lb]ERROR[rb][/color] ",
			LogLevel.Debug => "[color=SEA_GREEN][lb]DEBUG[rb][/color] ",
			_ => ""
		};
		AppendText($" {Time.GetUnixTimeFromSystem() - _startupTime:0.000} " + strLvl + message + "\n");
	}
}
