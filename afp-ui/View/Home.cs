using System.Collections.Generic;
using AFP.Core;
using Godot;
using Logger = AFP.Core.Logger;

namespace AFP.View;

public partial class Home : VBoxContainer
{
	private enum InfoId
	{
		ResourceName = 0,
		Status = 1,
		Channels = 2,
	}

	private Control _noScopeParent;
	private Tree _tree;
	private TreeItem _root;
	private Dictionary<string, TreeItem> _scopes = new();

	public override void _Ready()
	{
		_noScopeParent = GetNode<Control>("NoScopeParent");
		_tree = GetNode<Tree>("Tree");
		_tree.Columns = 2;
		_tree.SetColumnExpand(0, true);
		_tree.SetColumnExpandRatio(0, 1);
		_tree.SetColumnExpand(1, true);
		_tree.SetColumnExpandRatio(1, 3);
		_tree.HideRoot = true;
		_root = _tree.CreateItem();
		_root.SetExpandRight(0, true);
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

	private TreeItem CreateScopeTreeItem(string resourceName)
	{
		TreeItem item = _tree.CreateItem();
		item.SetExpandRight(0, true);
		TreeItem resourceItem = item.CreateChild((int)InfoId.ResourceName);
		resourceItem.SetText(0, "Resource");
		resourceItem.SetText(1, resourceName);
		TreeItem statusItem = item.CreateChild((int)InfoId.Status);
		statusItem.SetText(0, "Status");
		statusItem.SetText(1, "CONNECTING");
		TreeItem channelItem = item.CreateChild((int)InfoId.Channels);
		channelItem.SetText(0, "Channels");
		return item;
	}

	public void AddScope(string resourceName)
	{
		if (_scopes.ContainsKey(resourceName))
		{
			Global.Logger.Log(LogLevel.Warning, $"Ignoring {resourceName} (already exists)");
			return;
		}

		TreeItem item = CreateScopeTreeItem(resourceName);
		_scopes.Add(resourceName, item);

		if (!_tree.Visible)
		{
			_noScopeParent.Hide();
			_tree.Show();
		}
	}

	public void UpdateScope(string resourceName, string idn, ushort channelCount)
	{
		if (!_scopes.ContainsKey(resourceName))
		{
			AddScope(resourceName);
		}

		TreeItem item = _scopes[resourceName];
		item.SetText(0, idn);
		item.GetChild((int)InfoId.ResourceName).SetText(1, resourceName);
		item.GetChild((int)InfoId.Status).SetText(1, "CONNECTED");
		item.GetChild((int)InfoId.Channels).SetText(1, channelCount.ToString());
	}
}
