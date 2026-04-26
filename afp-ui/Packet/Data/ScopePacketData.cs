namespace AFP.Packet.Data;

public abstract class ScopePacketData : IPacketData
{
	public required string ResourceName { get; set; }
}
