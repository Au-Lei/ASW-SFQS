import { useEffect, useState, type KeyboardEvent } from 'react';
import type { BootstrapResponse } from '../../contracts/generated/contracts';
import { ApiError, loadWorkspace, verifySession } from './api/client';

const navigation = [
  { key: 'quotes', name: '报价总表', symbol: '▦' },
  { key: 'imports', name: '上传报价资料', symbol: '↥' },
  { key: 'review', name: '审核工作台', symbol: '☷' },
  { key: 'changes', name: '变更与导出', symbol: '⇄' },
  { key: 'search', name: '报价查询', symbol: '⌕' },
] as const;
type Page = (typeof navigation)[number]['key'];
const emptyPages: Record<
  Exclude<Page, 'quotes'>,
  { title: string; text: string; button: string }
> = {
  imports: {
    title: '让每份资料都有清晰的出处',
    text: '报价资料上传与识别尚未启用。后续可在这里整理 Excel、图片中的报价，并逐项核对原文。',
    button: '上传资料',
  },
  review: {
    title: '核对完成，再更新正式报价',
    text: '审核工作台尚未启用。后续识别结果将在这里保留原文、字段出处和待确认项。',
    button: '查看待审核记录',
  },
  changes: {
    title: '每次更新，都先看清变化',
    text: '变更预览与导出尚未启用。后续可对照旧值和新值确认更新，再导出六区域报价表。',
    button: '预览本次变更',
  },
  search: {
    title: '找到适合这次出运的方案',
    text: '报价查询尚未启用。正式报价接入后，可按目的港、船公司、柜型和报价有效期检索。',
    button: '查询报价',
  },
};

function currentPage(): Page {
  const value = window.location.hash.replace('#/', '');
  return navigation.find((item) => item.key === value)?.key ?? 'quotes';
}

export default function App() {
  const [page, setPage] = useState<Page>(currentPage);
  const [workspace, setWorkspace] = useState<BootstrapResponse | null>(null);
  const [regionId, setRegionId] = useState('');
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [checking, setChecking] = useState(false);
  const [connectionNote, setConnectionNote] = useState('');

  useEffect(() => {
    const update = () => setPage(currentPage());
    window.addEventListener('hashchange', update);
    return () => window.removeEventListener('hashchange', update);
  }, []);

  useEffect(() => {
    let active = true;
    loadWorkspace()
      .then((data) => {
        if (!active) return;
        setWorkspace(data);
        setRegionId(data.regions[0]?.id ?? '');
        setLoading(false);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setError(reason instanceof ApiError ? reason : new ApiError('加载失败，请重新检查连接。'));
        setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  async function reconnect() {
    setChecking(true);
    setConnectionNote('');
    try {
      const data = await loadWorkspace();
      await verifySession(data.csrf_token);
      setWorkspace(data);
      setError(null);
      setRegionId((old) => old || data.regions[0]?.id || '');
      setConnectionNote('本机服务与会话连接正常');
    } catch (reason) {
      setError(reason instanceof ApiError ? reason : new ApiError('连接检查失败。'));
    } finally {
      setChecking(false);
      setLoading(false);
    }
  }

  const selectedRegion = workspace?.regions.find((r) => r.id === regionId) ?? workspace?.regions[0];
  function onRegionKey(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const regions = workspace?.regions ?? [];
    if (!regions.length || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const nextIndex =
      event.key === 'Home'
        ? 0
        : event.key === 'End'
          ? regions.length - 1
          : (index + (event.key === 'ArrowRight' ? 1 : -1) + regions.length) % regions.length;
    const nextRegion = regions[nextIndex];
    setRegionId(nextRegion.id);
    document.getElementById(`tab-${nextRegion.id}`)?.focus();
  }
  const total = workspace?.regions.reduce((sum, region) => sum + region.destination_count, 0);
  const title = navigation.find((item) => item.key === page)?.name;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a href="#/quotes" className="brand" aria-label="ASW 海运报价工作台">
          <img src="/favicon.svg" width="39" height="39" alt="" />
          <span>
            <strong>ASW</strong>
            <small>海运报价工作台</small>
          </span>
        </a>
        <div className="workspace-label">工作空间</div>
        <div className="origin-card">
          <span className="origin-icon">青</span>
          <div>
            <strong>{workspace?.origin_name ?? '青岛港'}</strong>
            <span>国际海运 · 出口报价</span>
          </div>
          <i className="origin-dot" />
        </div>
        <nav aria-label="主要导航">
          {navigation.map((item) => (
            <a
              key={item.key}
              href={`#/${item.key}`}
              className={page === item.key ? 'nav-link active' : 'nav-link'}
              aria-current={page === item.key ? 'page' : undefined}
            >
              <span className="nav-symbol" aria-hidden="true">
                {item.symbol}
              </span>
              {item.name}
              {page === item.key && <span className="nav-indicator" />}
            </a>
          ))}
        </nav>
        <div className="sidebar-note">
          <span className="outline-icon">▤</span>
          <strong>六区域报价模板</strong>
          <p>
            统一格式，保留每条报价的
            <br />
            来源与适用条件。
          </p>
        </div>
        <div className="sidebar-footer">
          <span className="avatar">Q</span>
          <div>
            <strong>本机工作空间</strong>
            <small>ASW-SFQS · v0.1</small>
          </div>
        </div>
      </aside>

      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            青岛港<span>/</span>
            <strong>{title}</strong>
          </div>
          <div className="topbar-right">
            <span className={`status-dot ${workspace && !error ? 'online' : ''}`} />
            <span>{loading ? '正在连接服务' : error ? '服务连接异常' : '本机服务已连接'}</span>
            <span className="topbar-divider" />
            <span className="topbar-label">本机模式</span>
          </div>
        </header>
        <main>
          <div className="page-heading">
            <div>
              <div className="eyebrow">QINGDAO FREIGHT WORKSPACE</div>
              <h1>{title}</h1>
              <p>
                {page === 'quotes'
                  ? '从青岛出发，把分散的海运报价整理在一起。'
                  : '资料整理、人工审核与正式更新，逐步衔接。'}
              </p>
            </div>
            <div className="heading-actions">
              <button className="button secondary" onClick={reconnect} disabled={checking}>
                {checking ? '正在检查…' : '检查连接'}
              </button>
              <button className="button primary" disabled title="报价上传尚未启用">
                <span aria-hidden="true">＋</span> 新增报价
              </button>
            </div>
          </div>

          {error && (
            <div role="alert" className="error-banner">
              <strong>{error.message}</strong>
              {error.requestId && <small>请求编号：{error.requestId}</small>}
              <button className="text-button" onClick={reconnect} disabled={checking}>
                重试连接
              </button>
            </div>
          )}
          {connectionNote && !error && (
            <div role="status" className="connection-message">
              {connectionNote}
            </div>
          )}
          {loading ? (
            <section className="loading-panel" aria-busy="true">
              <span className="loader" />
              正在连接本机工作空间…
            </section>
          ) : page === 'quotes' ? (
            <>
              <section className="stat-grid" aria-label="工作空间概览">
                <div className="stat-card">
                  <span className="stat-label">预置目的地</span>
                  <div>
                    <strong>{total ?? '—'}</strong>
                    <span>个</span>
                  </div>
                  <p>来自已整理的港口模板</p>
                  <i className="stat-decoration" aria-hidden="true">
                    ⌁
                  </i>
                </div>
                <div className="stat-card">
                  <span className="stat-label">覆盖区域</span>
                  <div>
                    <strong>{workspace?.regions.length ?? '—'}</strong>
                    <span>个</span>
                  </div>
                  <p>按业务航线分区管理</p>
                  <i className="stat-decoration" aria-hidden="true">
                    ◎
                  </i>
                </div>
                <div className="stat-card">
                  <span className="stat-label">正式报价</span>
                  <div>
                    <strong className="pending-value">待接入</strong>
                  </div>
                  <p>报价数据库尚未初始化</p>
                  <span className="neutral-tag">尚未启用</span>
                </div>
              </section>

              <section className="catalog-card">
                <div className="section-heading">
                  <div>
                    <h2>航线与港口</h2>
                    <p>查看六区域预置目录，正式报价将在后续接入。</p>
                  </div>
                  <span className="subtle-label">预置目录</span>
                </div>
                <div className="region-tabs" role="tablist" aria-label="报价区域">
                  {workspace?.regions.map((region, index) => (
                    <button
                      key={region.id}
                      role="tab"
                      id={`tab-${region.id}`}
                      aria-controls="region-panel"
                      aria-selected={selectedRegion?.id === region.id}
                      tabIndex={selectedRegion?.id === region.id ? 0 : -1}
                      onKeyDown={(event) => onRegionKey(event, index)}
                      className={
                        selectedRegion?.id === region.id ? 'region-tab selected' : 'region-tab'
                      }
                      onClick={() => setRegionId(region.id)}
                    >
                      {region.name}
                      <span>{region.destination_count}</span>
                    </button>
                  ))}
                </div>
                {selectedRegion ? (
                  <div
                    role="tabpanel"
                    id="region-panel"
                    aria-labelledby={`tab-${selectedRegion.id}`}
                  >
                    <div className="region-summary">
                      <div>
                        <strong>{selectedRegion.name}</strong>
                        <span>
                          {selectedRegion.route_group_count} 个分组 ·{' '}
                          {selectedRegion.destination_count} 个目的地
                        </span>
                      </div>
                      <span className="catalog-only">目录已准备</span>
                    </div>
                    <div className="route-list">
                      {selectedRegion.route_names.map((name) => (
                        <span key={name}>{name}</span>
                      ))}
                    </div>
                    <div className="table-scroll">
                      <table>
                        <thead>
                          <tr>
                            <th>国家 / 地区</th>
                            <th>目的港英文名</th>
                            <th>目的港中文名</th>
                            <th>20GP</th>
                            <th>40GP</th>
                            <th>40HQ</th>
                            <th>报价状态</th>
                          </tr>
                        </thead>
                        <tbody>
                          {selectedRegion.preview_destinations.map((destination) => (
                            <tr key={destination.id}>
                              <td>{destination.country_zh}</td>
                              <td className="port-name">{destination.name_en}</td>
                              <td>{destination.name_zh}</td>
                              <td className="empty-price">—</td>
                              <td className="empty-price">—</td>
                              <td className="empty-price">—</td>
                              <td>
                                <span className="empty-tag">尚未接入报价</span>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <div className="table-footer">
                      <span>
                        仅预览前 {selectedRegion.preview_destinations.length}{' '}
                        个目的地，价格栏为占位，不表示零运价。
                      </span>
                      <span>完整目录与报价维护后续开放</span>
                    </div>
                  </div>
                ) : (
                  <div className="unavailable-panel">当前无法读取预置目录，请先恢复服务连接。</div>
                )}
              </section>
              <section className="bottom-grid">
                <div className="next-card">
                  <div className="small-square" aria-hidden="true">
                    ⇄
                  </div>
                  <div>
                    <h3>把每次报价更新变得清晰</h3>
                    <p>上传资料 → 核对记录 → 预览变化 → 更新与导出</p>
                    <span>正式更新功能尚未启用，当前展示基础目录。</span>
                  </div>
                </div>
                <div className="model-card">
                  <span className="model-icon" aria-hidden="true">
                    ✧
                  </span>
                  <div>
                    <h3>
                      {workspace?.model_status === 'ADAPTER_NOT_IMPLEMENTED'
                        ? '识别服务待接入'
                        : '模型服务未配置'}
                    </h3>
                    <p>
                      {workspace?.model_status === 'ADAPTER_NOT_IMPLEMENTED'
                        ? '已填写配置，自动识别尚未启用。'
                        : '不影响打开工作台和查看预置目录。'}
                    </p>
                  </div>
                  <span className="neutral-tag">未启用</span>
                </div>
              </section>
            </>
          ) : (
            <section className="feature-placeholder">
              <div className="placeholder-art" aria-hidden="true">
                <span />
                <span />
                <span />
                <b>＋</b>
              </div>
              <span className="neutral-tag">后续开放</span>
              <h2>{emptyPages[page].title}</h2>
              <p>{emptyPages[page].text}</p>
              <button className="button primary" disabled>
                {emptyPages[page].button}
              </button>
              <a href="#/quotes" className="text-button">
                返回报价总表
              </a>
            </section>
          )}
          <footer className="page-footer">
            <span>ASW-SFQS · 青岛海运报价</span>
            <span>报价有效期保留完整日期，导出时显示月日。</span>
          </footer>
        </main>
      </div>
    </div>
  );
}
