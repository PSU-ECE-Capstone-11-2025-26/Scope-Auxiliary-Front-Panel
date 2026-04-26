using Godot;

namespace AFP.View;

public partial class Home : VBoxContainer
{
	public string Status
	{
		get => _status;
		set
		{
			_status = value;
			_statusItem.SetText(1, value);
		}
	}

	private string _status;
	private TreeItem _resourceItem;
	private TreeItem _statusItem;
	private TreeItem _channelItem;
	private TreeItem _root;

	public override void _Ready()
	{
		var tree = GetNode<Tree>("Tree");
		tree.Columns = 2;
		tree.SetColumnExpand(0, true);
		tree.SetColumnExpandRatio(0, 1);
		tree.SetColumnExpand(1, true);
		tree.SetColumnExpandRatio(1, 3);
		_root = tree.CreateItem();
		_root.SetExpandRight(0, true);
		_resourceItem = _root.CreateChild();
		_resourceItem.SetText(0, "Resource");
		_statusItem = _root.CreateChild();
		_statusItem.SetText(0, "Status");
		_channelItem = _root.CreateChild();
		_channelItem.SetText(0, "Channels");

		SetScope("No Scope", "?", 0);
		Status = "DISCONNECTED";
	}

	public void SetScope(string idn, string resourceName, ushort channelCount)
	{
		_root.SetText(0, idn);
		_resourceItem.SetText(1, resourceName);
		_channelItem.SetText(1, channelCount.ToString());
		Status = "CONNECTED";
	}
}
