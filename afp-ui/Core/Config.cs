using System.Collections.Generic;

namespace AFP.Core;

public enum AutoConnectMode : byte
{
	None = 0,
	LastUsed = 1,
	FirstAvailable = 2,
}

public class Config
{
    public string WebSocketUrl { get; init; } = "ws://127.0.0.1:8000/ws";
    public AutoConnectMode AutoConnect { get; set; } = AutoConnectMode.None;
    public List<string> LastUsedScopes { get; init; } = [];
    public bool DebugMode { get; set; }
}
