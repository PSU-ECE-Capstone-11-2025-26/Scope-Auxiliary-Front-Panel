using System.Text.Json;
using System.Text.Json.Serialization;
using Godot;

namespace AFP.Core;

public partial class Global : Node
{
	public static Logger Logger { get; } = new();
    public static Global Instance { get; private set; }
    /// <summary>
    /// Path to the config file
    /// </summary>
    private const string ConfigPath = "user://ui.json";
    /// <summary>
    /// The config for the UI
    /// </summary>
    public Config Config { get; private set; }
    
    public Control Toast { get; set; }

    private static readonly JsonSerializerOptions JsonSerializerOptions = new()
    {
        PropertyNameCaseInsensitive = true,
        DefaultIgnoreCondition = JsonIgnoreCondition.Never,
        WriteIndented = true
    };

    public override void _Ready()
    {
        Instance = this;
        Logger.OnToast += OnToast;
    }

    public override void _ExitTree()
    {
	    SaveConfig();
    }

    private void OnToast(LogLevel level, string message)
    {
	    Toast.Call("add_message_compat", (ushort)level, message);
    }

    /// <summary>
    /// Initialize the config file with default options
    /// </summary>
    private void InitConfig()
    {
        Config = new Config();
        SaveConfig(true);
    }
    
    /// <summary>
    /// Load the config file into memory
    /// </summary>
    public void LoadConfig()
    {
        if (!FileAccess.FileExists(ConfigPath))
        {
            InitConfig();
            return;
        }
        
        using FileAccess file = FileAccess.Open(ConfigPath, FileAccess.ModeFlags.Read);

        string raw = file.GetAsText();
        
        Config = JsonSerializer.Deserialize<Config>(raw);
        if (Config == null)
        {
            InitConfig();
        }
    }

    /// <summary>
    /// Write the config to disk
    /// </summary>
    public void SaveConfig(bool flush = false)
    {
        using FileAccess file = FileAccess.Open(ConfigPath, FileAccess.ModeFlags.Write);
        string json = JsonSerializer.Serialize(Config, JsonSerializerOptions);
        file.StoreString(json);
        if (flush) file.Flush();
    }
}
