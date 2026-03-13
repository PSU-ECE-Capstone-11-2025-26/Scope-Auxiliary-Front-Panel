using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace AFP.Packet;

public enum ScopeStatus
{
	Connected,
	Disconnected,
	Connecting,
}

public class PacketContainer
{
	public List<PacketBase> Packets { get; set; } = [];
}

[JsonDerivedType(typeof(ScopeInfoPacket), typeDiscriminator: "ScopeInfoPacket")]
[JsonDerivedType(typeof(ScopeStatePacket), typeDiscriminator: "ScopeStatePacket")]
[JsonDerivedType(typeof(ScopeListPacket), typeDiscriminator: "ScopeListPacket")]
[JsonDerivedType(typeof(MacroRecordPacket), typeDiscriminator: "MacroRecordPacket")]
[JsonDerivedType(typeof(MacroStatePacket), typeDiscriminator: "MacroStatePacket")]
[JsonDerivedType(typeof(ScopeActionPacket), typeDiscriminator: "ScopeActionPacket")]
public class PacketBase
{
    public required string From { get; set; }
}

public class ScopeInfoPacket : PacketBase
{
	public required ushort ChannelCount { get; set; }
}

public class ScopeStatePacket : PacketBase
{
	public required ScopeStatus Status { get; set; }
	public required bool[] Channels { get; set; }
	public required ushort SourceChannel { get; set; }
	public required ushort TriggerSource { get; set; }
	public required string TriggerMode { get; set; }
	public required string TriggerEdgeSlope { get; set; }
	public required bool RunStop { get; set; }
	public required bool ZoomEnabled { get; set; }
}

public class ScopeListPacket : PacketBase
{
	public required string[] Scopes { get; set; }
}

public class MacroRecordPacket : PacketBase
{
	public required bool Record { get; set; }
	public required ushort Slot { get; set; }
}

public class MacroStatePacket : PacketBase
{
	public required bool[] Macros { get; set; }
}

public class ScopeActionPacket : PacketBase
{
	public required string Action { get; set; }
	public required string Scope { get; set; }
}
