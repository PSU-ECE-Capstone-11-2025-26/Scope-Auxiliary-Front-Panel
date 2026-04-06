namespace AFP.Packet;

public class ScopeListPacketData : IPacketData
{
	public required string[] Scopes { get; set; }
}