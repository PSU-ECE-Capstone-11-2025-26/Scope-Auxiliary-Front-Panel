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
	public required string From { get; set; }
	public required List<IPacketData> Data { get; set; }
}

[JsonDerivedType(typeof(ScopeInfoPacketData), typeDiscriminator: "ScopeInfo")]
[JsonDerivedType(typeof(ScopeStatePacketData), typeDiscriminator: "ScopeState")]
[JsonDerivedType(typeof(ScopeListPacketData), typeDiscriminator: "ScopeList")]
[JsonDerivedType(typeof(MacroRecordPacketData), typeDiscriminator: "MacroRecord")]
[JsonDerivedType(typeof(MacroStatePacketData), typeDiscriminator: "MacroState")]
[JsonDerivedType(typeof(ScopeActionPacketData), typeDiscriminator: "ScopeAction")]
public interface IPacketData {}

public class ScopeInfoPacketData : IPacketData
{
	public required ushort ChannelCount { get; set; }
}

public class ScopeStatePacketData : IPacketData
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

public class ScopeListPacketData : IPacketData
{
	public required string[] Scopes { get; set; }
}

public class MacroRecordPacketData : IPacketData
{
	public required bool Record { get; set; }
	public required ushort Slot { get; set; }
}

public class MacroStatePacketData : IPacketData
{
	public required bool[] Macros { get; set; }
}

public class ScopeActionPacketData : IPacketData
{
	public required string Action { get; set; }
	public required string Scope { get; set; }
}
