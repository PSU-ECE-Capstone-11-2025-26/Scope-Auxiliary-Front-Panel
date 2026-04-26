using System.Collections.Generic;
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
	private Control _noScopeParent;
	private Tree _tree;
	private TreeItem _resourceItem;
	private TreeItem _statusItem;
	private TreeItem _channelItem;
	private TreeItem _root;
	private List<string> _scopes = [];

	public override void _Ready()
	{
		_noScopeParent = GetNode<Control>("NoScopeParent");
		_tree = GetNode<Tree>("Tree");
		_tree.Columns = 2;
		_tree.SetColumnExpand(0, true);
		_tree.SetColumnExpandRatio(0, 1);
		_tree.SetColumnExpand(1, true);
		_tree.SetColumnExpandRatio(1, 3);
		_root = _tree.CreateItem();
		_root.SetExpandRight(0, true);
		_resourceItem = _root.CreateChild();
		_resourceItem.SetText(0, "Resource");
		_statusItem = _root.CreateChild();
		_statusItem.SetText(0, "Status");
		_channelItem = _root.CreateChild();
		_channelItem.SetText(0, "Channels");
	}

	public void RemoveScope(string resourceName)
	{
		_scopes.Remove(resourceName);
		if (_scopes.Count == 0)
		{
			_tree.Hide();
			_noScopeParent.Show();
		}
	}

	public void AddScope(string resourceName)
	{
		if (_scopes.Contains(resourceName))
		{
			Core.Global.Instance.Log(1, $"Ignoring {resourceName} (already exists)");
		}
		else if (!_tree.Visible)
		{
			_noScopeParent.Hide();
			_tree.Show();
		}
		_scopes.Add(resourceName);
		_resourceItem.SetText(1, resourceName);
		Status = "CONNECTING";
	}

	public void UpdateScope(string resourceName, string idn, ushort channelCount)
	{
		if (!_scopes.Contains(resourceName))
		{
			AddScope(resourceName);
		}
		_root.SetText(0, idn);
		_channelItem.SetText(1, channelCount.ToString());
		Status = "CONNECTED";
	}
}
