namespace AFP.Packet;

public class ScopeActionPacketData : IPacketData
{
	public required string Action { get; set; }
	public required string Scope { get; set; }
}
