namespace AFP.Packet.Data;

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
