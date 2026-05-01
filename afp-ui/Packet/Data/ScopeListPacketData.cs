using System.Collections.Generic;

namespace AFP.Packet.Data;

public class ScopeListPacketData : IPacketData
{
	public required Dictionary<string, bool> Scopes { get; set; }
}

