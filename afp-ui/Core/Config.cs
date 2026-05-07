namespace AFP.Core;

public class Config
{
    public string WebSocketUrl { get; set; } = "ws://127.0.0.1:8000/ws";
    public bool SaveSelectedScopes { get; set; } = true;
    public bool DebugMode { get; set; }
}
