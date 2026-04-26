namespace AFP.Core;

public enum LogLevel : ushort
{
	Info = 0,
	Warning = 1,
	Error = 2,
	Debug = 3,
}

public class Logger
{
	public delegate void LogMessageHandler(LogLevel level, string message);

	public event LogMessageHandler OnLog;
	public event LogMessageHandler OnToast;

	public void Log(LogLevel logLevel, string msg, bool toast = false)
	{
		if (!Global.Instance.Config.DebugMode && logLevel == LogLevel.Debug) return;
		OnLog?.Invoke(logLevel, msg);
		if (toast)
		{
			OnToast?.Invoke(logLevel, msg);
		}
	}
}
