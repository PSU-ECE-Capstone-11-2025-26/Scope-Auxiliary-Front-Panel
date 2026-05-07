namespace AFP.Packet.Data;

public class ScopeListPacketData : IPacketData
{
	public required string[] Scopes { get; set; }
}