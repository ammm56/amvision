/** 图片与字段关联操作；节点端口名保持英文，页面操作随界面语言切换。 */
export const presentationMessages = {
  'zh-CN': {
    standalone: '独立面板',
    imagePanel: '显示图片面板', dataPanel: '显示数据面板', separatePanel: '显示独立面板', extraPanel: '另加独立面板',
    presentation: '图片内数据', imageOnly: '无 · 仅图片', disabled: '已禁用',
    shownWith: '随图显示', connectedHidden: '已连接，图片面板未显示', notOnPage: '未在此页面显示',
    targets: '关联图片', noTargets: '未连接图片，可独立显示', locate: '定位', panelTitle: '面板标题', panelSize: '面板大小',
  },
  'en-US': {
    standalone: 'Separate panels',
    imagePanel: 'Show image panel', dataPanel: 'Show data panel', separatePanel: 'Show separate panel', extraPanel: 'Add separate panel',
    presentation: 'Image data', imageOnly: 'None · Image only', disabled: 'Disabled',
    shownWith: 'Shown with', connectedHidden: 'Connected; image panel hidden', notOnPage: 'Not shown on this page',
    targets: 'Connected images', noTargets: 'No connected images; separate panel available', locate: 'Locate', panelTitle: 'Panel title', panelSize: 'Panel size',
  },
  'ja-JP': {
    standalone: '独立パネル',
    imagePanel: '画像パネルを表示', dataPanel: 'データパネルを表示', separatePanel: '独立パネルを表示', extraPanel: '独立パネルを追加',
    presentation: '画像内のデータ', imageOnly: 'なし・画像のみ', disabled: '無効',
    shownWith: '画像と一緒に表示', connectedHidden: '接続済み・画像パネルは非表示', notOnPage: 'このページには表示されません',
    targets: '接続先の画像', noTargets: '画像未接続・独立表示可能', locate: '移動', panelTitle: 'パネルタイトル', panelSize: 'パネルサイズ',
  },
  'ko-KR': {
    standalone: '독립 패널',
    imagePanel: '이미지 패널 표시', dataPanel: '데이터 패널 표시', separatePanel: '독립 패널 표시', extraPanel: '독립 패널 추가',
    presentation: '이미지 내 데이터', imageOnly: '없음 · 이미지만', disabled: '비활성',
    shownWith: '이미지와 함께 표시', connectedHidden: '연결됨 · 이미지 패널 숨김', notOnPage: '이 페이지에 표시되지 않음',
    targets: '연결된 이미지', noTargets: '연결된 이미지 없음 · 독립 표시 가능', locate: '찾기', panelTitle: '패널 제목', panelSize: '패널 크기',
  },
}
