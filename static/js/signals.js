// ── SSE 스트리밍 ──────────────────────────────────────────────

let _evtSource = null;

function _startStream(tickers) {
  const area = document.getElementById('signal-result-area');
  if (_evtSource) _evtSource.close();

  const params = new URLSearchParams();
  if (tickers && tickers.length) params.set('tickers', tickers.join(','));

  area.innerHTML = '<div class="polling"><p class="status-text">⏳ 시그널 분석 중...</p></div>';

  _evtSource = new EventSource(`/stream/signals?${params}`);

  _evtSource.addEventListener('progress', function (e) {
    const data = JSON.parse(e.data);
    area.innerHTML = `<div class="polling"><p class="status-text">⏳ ${data.stage}</p></div>`;
  });

  _evtSource.addEventListener('done', function (e) {
    _evtSource.close();
    _evtSource = null;
    const data = JSON.parse(e.data);
    area.innerHTML = data.html;
    _syncWatchlistTags(data.watchlist || []);
    _applyFilter(_currentFilter);
    _markSignalWatchlistBtns();
    // subtitle 갱신 시각 업데이트
    const updEl = document.getElementById('signal-updated');
    if (updEl) {
      const now = new Date();
      const hh  = String(now.getHours()).padStart(2, '0');
      const mm  = String(now.getMinutes()).padStart(2, '0');
      updEl.textContent = `${hh}:${mm} 기준`;
    }
  });

  _evtSource.addEventListener('error', function (e) {
    _evtSource.close();
    _evtSource = null;
    try {
      const data = JSON.parse(e.data);
      area.innerHTML = `<div class="error-box"><p>❌ 오류: ${data.message}</p></div>`;
    } catch {
      area.innerHTML = '<div class="error-box"><p>❌ 알 수 없는 오류가 발생했습니다.</p></div>';
    }
  });
}

// ── 필터 ─────────────────────────────────────────────────────

let _currentFilter = 'all';

function _applyFilter(filter) {
  _currentFilter = filter;
  document.querySelectorAll('#signal-result-area .signal-card').forEach(card => {
    const grade = card.dataset.signalGrade;
    card.style.display = (filter === 'all' || grade === filter) ? '' : 'none';
  });
}

document.querySelectorAll('.sig-filter-bar .pill').forEach(btn => {
  btn.addEventListener('click', function () {
    document.querySelectorAll('.sig-filter-bar .pill').forEach(b => b.classList.remove('is-active'));
    this.classList.add('is-active');
    _applyFilter(this.dataset.filter);
  });
});

// ── Watchlist 태그 ───────────────────────────────────────────

function _getTagTickers() {
  return [...document.querySelectorAll('#watchlist-tags .wl-tag')].map(t => t.dataset.ticker);
}

function _addTag(ticker) {
  ticker = ticker.trim().toUpperCase();
  if (!ticker) return;
  const tags = document.getElementById('watchlist-tags');
  if (tags.querySelector(`[data-ticker="${ticker}"]`)) return;  // 이미 있음

  const span = document.createElement('span');
  span.className = 'wl-tag';
  span.dataset.ticker = ticker;
  span.innerHTML = `${ticker}<button class="wl-remove" data-ticker="${ticker}" aria-label="삭제">×</button>`;
  tags.appendChild(span);
}

function _removeTag(ticker) {
  const el = document.querySelector(`#watchlist-tags .wl-tag[data-ticker="${ticker}"]`);
  if (el) el.remove();
}

function _syncWatchlistTags(tickers) {
  const tags = document.getElementById('watchlist-tags');
  tags.innerHTML = '';
  tickers.forEach(t => _addTag(t));
  if (!tickers.length) {
    const hint = document.createElement('span');
    hint.className = 'wl-empty-hint';
    hint.textContent = '종목 없음 — Finviz 상위 30개로 자동 분석합니다';
    tags.appendChild(hint);
  }
}

// 태그 삭제 클릭 (이벤트 위임)
document.getElementById('watchlist-tags').addEventListener('click', async function (e) {
  const btn = e.target.closest('.wl-remove');
  if (!btn) return;
  const ticker = btn.dataset.ticker;
  _removeTag(ticker);
  await fetch(`/api/watchlist/${ticker}`, { method: 'DELETE' });
  // 남은 종목으로 재분석
  const remaining = _getTagTickers();
  if (remaining.length) _startStream(remaining);
  else _startStream([]); // 전체 랭킹으로 복구
});

// 추가 버튼
document.getElementById('wl-add-btn').addEventListener('click', async function () {
  const input = document.getElementById('wl-input');
  const ticker = input.value.trim().toUpperCase();
  if (!ticker) return;
  input.value = '';

  const res = await fetch(`/api/watchlist/${ticker}`, { method: 'POST' });
  const data = await res.json();
  _syncWatchlistTags(data.tickers);
  _startStream(data.tickers);
});

// Enter 키
document.getElementById('wl-input').addEventListener('keydown', function (e) {
  if (e.key === 'Enter') document.getElementById('wl-add-btn').click();
});

// ↻ 분석 버튼
document.getElementById('wl-refresh-btn').addEventListener('click', function () {
  const tickers = _getTagTickers();
  _startStream(tickers);
});

// ── 차트 모달 ─────────────────────────────────────────────

let _lwChart      = null;
let _candleSeries = null;
let _allMarkers   = [];

document.addEventListener('click', function (e) {
  const btn = e.target.closest('.chart-btn');
  if (!btn) return;
  const card = btn.closest('.signal-card') || btn.closest('.stock-card');
  if (!card) return;
  _openModal(card);
});

function _openModal(card) {
  const ticker = card.dataset.ticker;
  const info   = card.dataset.info ? JSON.parse(card.dataset.info) : null;

  document.getElementById('modal-ticker').textContent = ticker;

  // 종목 정보 바 (이름 · 가격 · 등락)
  const stockInfo = document.getElementById('modal-stock-info');
  if (info) {
    const sign    = info.change >= 0 ? '▲' : '▼';
    const cls     = info.change >= 0 ? 'up' : 'down';
    const price   = (info.price || 0).toFixed(2);
    const chg     = Math.abs(info.change || 0).toFixed(2);
    const company = info.short_name || '';
    stockInfo.innerHTML =
      `<span class="msi-ticker">${ticker}</span>` +
      `<span class="msi-company">${company}</span>` +
      `<span class="msi-price">$${price}</span>` +
      `<span class="msi-change ${cls}">${sign} ${chg}%</span>`;
  } else {
    stockInfo.innerHTML = '';
  }

  // 기간 버튼 초기화 (6M)
  document.querySelectorAll('.period-btn').forEach(b => {
    b.classList.toggle('is-active', b.dataset.period === '6mo');
  });

  // 시그널 지표
  _renderSignalDetail(info);

  document.getElementById('chart-modal').classList.add('is-open');
  _fetchAndRenderChart(ticker, '6mo');
}

function _renderSignalDetail(info) {
  const detail = document.getElementById('modal-detail');
  if (!info || !info.grade) { detail.innerHTML = ''; return; }

  const GRADE_CLS  = { 'STRONG BUY': 'grade-strong-buy', 'BUY': 'grade-buy', 'WATCH': 'grade-watch', 'NO SIGNAL': 'grade-nosignal' };
  const CAT_LABELS = { entry: '진입', momentum: '모멘텀', structure: '구조', volume: '수급' };

  const gradeCls = GRADE_CLS[info.grade] || 'grade-nosignal';
  const score    = Math.round((info.score || 0) * 100);
  const zone     = (info.entry_low && info.entry_high)
    ? `$${info.entry_low.toFixed(2)} – ${info.entry_high.toFixed(2)}`
    : '–';

  const bkd  = info.breakdown || {};
  const cats = Object.entries(CAT_LABELS).map(([key, label]) => {
    const val  = bkd[key] || 0;
    const pct  = Math.round(val * 100);
    const tone = val >= 0.75 ? '' : val >= 0.5 ? 'tone-watch' : val >= 0.25 ? 'tone-bear' : 'tone-mute';
    return `<div class="msd-cat">` +
      `<div class="msd-cat-head"><span>${label}</span><span>${pct}</span></div>` +
      `<div class="sc-bar"><div class="sc-bar-fill ${tone}" style="width:${pct}%"></div></div>` +
      `</div>`;
  }).join('');

  const patterns = (info.patterns || []).length
    ? info.patterns.map(p => `<span class="msd-pattern">${p}</span>`).join('')
    : '<span class="msd-no-pattern">감지된 패턴 없음</span>';

  // Confluence panel
  const CF_META = {
    structure: { icon: '◆', label: '구조 지지' },
    momentum:  { icon: '▲', label: '모멘텀 회복' },
    flow:      { icon: '→', label: '자금 유입' },
  };
  const cfCount  = info.confluence_count  || 0;
  const cfDetail = info.confluence_detail || {};
  let cfSection  = '';
  if (cfCount > 0) {
    const cfRows = Object.entries(CF_META).map(([key, meta]) => {
      const d   = cfDetail[key] || {};
      const ok  = d.ok || false;
      return `<div class="cf-detail-row ${ok ? 'cf-row-ok' : 'cf-row-fail'}">` +
        `<span class="cf-row-icon">${meta.icon}</span>` +
        `<span class="cf-row-label">${meta.label}</span>` +
        `<span class="cf-row-check">${ok ? '✓' : '✗'}</span>` +
        `<span class="cf-row-reason">${d.reason || ''}</span>` +
        `</div>`;
    }).join('');
    const maxNote = cfCount === 3
      ? `<p class="cf-maxed-note">3가지 독립 신호 동시 충족 — 최고 신뢰도 진입입니다.</p>`
      : '';
    cfSection =
      `<div class="msd-confluence">` +
      `  <div class="cf-header">` +
      `    <span class="cf-header-title">CONFLUENCE</span>` +
      `    <span class="cf-header-score">${cfCount} / 3</span>` +
      `  </div>` +
      `  <div class="cf-detail-rows">${cfRows}</div>` +
      maxNote +
      `</div>`;
  }

  detail.innerHTML =
    `<div class="modal-signal-section">` +
    `  <div class="msd-header">` +
    `    <span class="msd-badge ${gradeCls}">${info.grade}</span>` +
    `    <span class="msd-score">SCORE <b>${score}</b>/100</span>` +
    `    <span class="msd-zone"><span class="lbl">ENTRY</span><span class="val">${zone}</span></span>` +
    `  </div>` +
    `  <div class="msd-cats">${cats}</div>` +
    `  <div class="msd-patterns-row">${patterns}</div>` +
    cfSection +
    `</div>`;
}

function _closeModal() {
  document.getElementById('chart-modal').classList.remove('is-open');
  document.getElementById('marker-tooltip').style.display = 'none';
  if (_lwChart) {
    _lwChart.remove();
    _lwChart = null;
    _candleSeries = null;
    _allMarkers   = [];
  }
}

// LWC v4: string "YYYY-MM-DD" → BusinessDay 객체로 변환되어 반환됨
function _timeToStr(t) {
  if (!t) return null;
  if (typeof t === 'string') return t;
  if (t.year) return `${t.year}-${String(t.month).padStart(2,'0')}-${String(t.day).padStart(2,'0')}`;
  return null;
}

async function _fetchAndRenderChart(ticker, period = '6mo') {
  const container = document.getElementById('lw-chart-container');
  container.innerHTML = '<p style="color:var(--text3);padding:1rem;text-align:center">차트 로딩 중...</p>';
  try {
    const res = await fetch(`/api/chart-data/${ticker}?period=${period}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    if (_lwChart) _lwChart.remove();
    container.innerHTML = '';

    const chart = LightweightCharts.createChart(container, {
      autoSize: true,
      layout: { background: { color: '#0f1117' }, textColor: '#94a3b8' },
      grid: { vertLines: { color: 'rgba(255,255,255,0.03)' }, horzLines: { color: 'rgba(255,255,255,0.03)' } },
      crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
      rightPriceScale: { borderColor: 'rgba(255,255,255,0.07)' },
      timeScale: { borderColor: 'rgba(255,255,255,0.07)', timeVisible: true },
    });
    _lwChart = chart;

    const volSeries = chart.addHistogramSeries({
      priceScaleId: 'volume', priceFormat: { type: 'volume' },
      scaleMargins: { top: 0.85, bottom: 0 },
    });
    volSeries.setData(data.ohlcv.map(b => ({
      time: b.time, value: b.volume,
      color: b.close >= b.open ? 'rgba(52,211,153,0.15)' : 'rgba(244,63,94,0.15)',
    })));

    const candle = chart.addCandlestickSeries({
      upColor: '#10b981', downColor: '#f43f5e',
      borderUpColor: '#10b981', borderDownColor: '#f43f5e',
      wickUpColor: '#10b981', wickDownColor: '#f43f5e',
    });
    candle.setData(data.ohlcv);
    _candleSeries = candle;

    if (data.ma60 && data.ma60.length) {
      chart.addLineSeries({
        color: 'rgba(251,191,36,0.65)', lineWidth: 1,
        priceLineVisible: false, lastValueVisible: false,
      }).setData(data.ma60);
    }

    if (data.ma20 && data.ma20.length) {
      chart.addLineSeries({
        color: 'rgba(99,179,237,0.8)', lineWidth: 1,
        priceLineVisible: false, lastValueVisible: false,
      }).setData(data.ma20);
    }

    _allMarkers = data.markers || [];
    _applyMarkers();

    // 마커 호버 툴팁
    const tooltip = document.getElementById('marker-tooltip');
    chart.subscribeCrosshairMove(param => {
      if (!param.time || !param.point) {
        tooltip.style.display = 'none';
        return;
      }
      const timeStr = _timeToStr(param.time);
      const marker  = _allMarkers.find(m => m.time === timeStr);
      if (!marker) {
        tooltip.style.display = 'none';
        return;
      }
      const isBuy  = marker.type === 'buy';
      const reason = marker.reason || (isBuy ? '매수 신호' : '매도 신호');
      tooltip.className = `marker-tooltip type-${marker.type}`;
      tooltip.innerHTML =
        `<div class="mt-type">${isBuy ? '▲ BUY' : '▼ SELL'}</div>` +
        `<div class="mt-reason">${reason}</div>` +
        `<div class="mt-meta">${timeStr} · $${marker.price.toFixed(2)}</div>`;

      const rect = document.getElementById('lw-chart-container').getBoundingClientRect();
      const x    = rect.left + param.point.x + 14;
      const y    = rect.top  + param.point.y - 72;
      tooltip.style.left    = `${Math.min(x, window.innerWidth - 160)}px`;
      tooltip.style.top     = `${Math.max(y, rect.top + 8)}px`;
      tooltip.style.display = 'block';
    });

  } catch (err) {
    container.innerHTML = `<p style="color:#f87171;padding:1rem;text-align:center">차트 로드 실패: ${err.message}</p>`;
  }
}

function _applyMarkers() {
  if (!_candleSeries) return;
  const markers = _allMarkers.map(m => ({
    time:     m.time,
    position: m.type === 'buy' ? 'belowBar' : 'aboveBar',
    shape:    m.type === 'buy' ? 'arrowUp'  : 'arrowDown',
    color:    m.type === 'buy' ? '#34d399'  : '#f87171',
    text:     m.type === 'buy' ? 'B' : 'S',
    size: 1,
  }));
  _candleSeries.setMarkers(markers);
}

// 기간 선택 버튼
document.querySelector('.modal-period-bar').addEventListener('click', function (e) {
  const btn = e.target.closest('.period-btn');
  if (!btn) return;
  this.querySelectorAll('.period-btn').forEach(b => b.classList.remove('is-active'));
  btn.classList.add('is-active');
  const ticker = document.getElementById('modal-ticker').textContent;
  _fetchAndRenderChart(ticker, btn.dataset.period);
});

document.getElementById('modal-close').addEventListener('click', _closeModal);
document.getElementById('chart-modal').addEventListener('click', function (e) {
  if (e.target === this) _closeModal();
});
document.addEventListener('keydown', function (e) {
  if (e.key === 'Escape') _closeModal();
});

// ── 시그널 카드 ★ Watchlist 추가 ────────────────────────────

function _markSignalWatchlistBtns() {
  const wlSet = new Set(_getTagTickers());
  document.querySelectorAll('#signal-result-area .watchlist-btn').forEach(btn => {
    btn.classList.toggle('wl-added', wlSet.has(btn.dataset.ticker));
  });
}

document.getElementById('signal-result-area').addEventListener('click', async function (e) {
  const btn = e.target.closest('.watchlist-btn');
  if (!btn) return;
  const ticker = btn.dataset.ticker;

  if (btn.classList.contains('wl-added')) return; // 이미 추가됨

  try {
    const res = await fetch(`/api/watchlist/${ticker}`, { method: 'POST' });
    const data = await res.json();
    _addTag(ticker);
    btn.classList.add('wl-added');
    btn.title = 'Watchlist에 추가됨';
  } catch {}
});

// ── 페이지 로드 시 자동 분석 ─────────────────────────────────

(function () {
  const tickers = _getTagTickers();
  _startStream(tickers);
})();
