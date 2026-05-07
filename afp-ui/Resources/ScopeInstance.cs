using Godot;

namespace AFP.Resources;

public enum ScopeConnectionState
{
	Disconnected = 0,
	Connecting = 1,
	Connected = 2,
}

public partial class ScopeInstance : Resource
{
	public ScopeInstance()
	{
	}

	public ScopeInstance(string visaResourceName, string idn, ScopeConnectionState connectionState, ushort channelCount)
	{
		VisaResourceName = visaResourceName;
		Idn = idn;
		ConnectionState = connectionState;
		ChannelCount = channelCount;
	}

	[Export] public string VisaResourceName { get; private set; }
	[Export] public string Idn { get; set; }
	public ScopeConnectionState ConnectionState { get; set; } = ScopeConnectionState.Connecting;
	[Export] public ushort ChannelCount { get; set; }
}
