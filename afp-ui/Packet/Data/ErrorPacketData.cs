namespace AFP.Packet.Data;

public class ErrorPacketData : ScopePacketData
{
	public required int ErrorCode { get; set; }
	public required string ErrorStr { get; set; }
}
