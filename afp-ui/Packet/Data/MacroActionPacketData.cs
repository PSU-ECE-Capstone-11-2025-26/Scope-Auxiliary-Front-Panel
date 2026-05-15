namespace AFP.Packet.Data;

public enum MacroAction
{
	Record = 0,
	Save = 1,
	Delete = 2,
}

public class MacroActionPacketData : IPacketData
{
	public required MacroAction Action { get; set; }
	public required ushort Slot { get; set; }
}
