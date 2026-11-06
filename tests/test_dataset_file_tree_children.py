"""版本文件树必须正确区分空目录、仅包含文件的目录和文件叶子。"""
from backend.service.application.datasets.workspace_files import list_version_files


def test_file_tree_children(tmp_path):
    """直接返回子项标记，首次展开前即可隐藏空目录箭头。"""
    (tmp_path / 'empty').mkdir()
    (tmp_path / 'images').mkdir()
    (tmp_path / 'images' / 'a.jpg').write_bytes(b'image')
    (tmp_path / 'meta.json').write_text('{}')
    page = list_version_files(tmp_path, '', after='', limit=20)
    rows = {item['name']: item for item in page['items']}
    assert rows['empty']['has_children'] is False
    assert rows['images']['has_children'] is True
    assert rows['meta.json']['directory'] is False
    assert rows['meta.json']['has_children'] is None
    folders = list_version_files(tmp_path, '', after='', limit=20, directories_only=True)
    assert all(item['has_directories'] is False for item in folders['items'])
