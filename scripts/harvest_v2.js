/**
 * 关键词批量抓取器（走站内搜索 API）
 *
 * 原理：复用已登录的浏览器（CDP 9222），在页面上下文里调站内搜索 API，
 *      拿到完整 stats（playCount/diggCount/commentCount/shareCount/collectCount）。
 *      —— 不依赖第三方库、不用 ms_token、不需要解析 DOM。
 *
 * 用法（关键词必填，脚本不自带任何默认词）：
 *   node harvest_v2.js "kw1,kw2,kw3"        # 抓这些词
 *   node harvest_v2.js "kw1,kw2" --pages=3  # 每词抓 3 页（默认 2 页 × 20 条）
 *
 * 产出：harvest_v2.json + 控制台爆款排行（写在当前工作目录）
 */
// 依赖：playwright-core。在装有该模块的项目目录下运行，例如
//   cd <项目> && node <skill>/scripts/harvest_v2.js "kw1,kw2"
// 产出文件写在当前工作目录（cwd），不写进 skill 目录。
const fs = require('fs');
const path = require('path');

const OUT = path.join(process.cwd(), 'harvest_v2.json');

const sleep = ms => new Promise(r => setTimeout(r, ms));
const rnd = (a, b) => a + Math.random() * (b - a);

const args = process.argv.slice(2);
const pagesArg = args.find(a => a.startsWith('--pages='));
const PAGES = pagesArg ? parseInt(pagesArg.split('=')[1], 10) : 2;
const kwArg = args.find(a => !a.startsWith('--'));
if (!kwArg) {
  console.log('用法: node harvest_v2.js "kw1,kw2,kw3" [--pages=N]');
  console.log('关键词没有默认值，必须自己给。');
  process.exit(1);
}
const KEYWORDS = kwArg.split(',').map(s => s.trim()).filter(Boolean);

(async () => {
  const { chromium } = require('playwright-core');   // 延迟到用时再 require，缺依赖不影响看用法
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const ctx = browser.contexts()[0];
  const page = ctx.pages().find(p => p.url().includes('tiktok.com')) || ctx.pages()[0];
  if (!page) throw new Error('没有可用的目标站点页面');
  await page.bringToFront();

  // 确认登录态
  const ck = await ctx.cookies('https://www.tiktok.com');
  const logged = !!ck.find(c => c.name === 'sessionid' || c.name === 'sid_tt');
  console.log(`登录态: ${logged ? 'OK' : '未登录(仍可搜索,但结果可能受限)'}`);
  console.log(`关键词: ${KEYWORDS.length} 个 × ${PAGES} 页\n`);

  const bag = new Map();   // id -> record
  const kwStat = [];

  for (const kw of KEYWORDS) {
    let got = 0;
    for (let pg = 0; pg < PAGES; pg++) {
      const offset = pg * 20;
      let payload = null;
      // 单页最多重试 3 次
      for (let attempt = 1; attempt <= 3; attempt++) {
        payload = await page.evaluate(async ({ kw, offset }) => {
          const url = 'https://www.tiktok.com/api/search/general/full/?keyword=' +
            encodeURIComponent(kw) + '&count=20&offset=' + offset;
          try {
            const res = await fetch(url, { credentials: 'include' });
            const txt = await res.text();
            try { return JSON.parse(txt); } catch (e) { return { _raw: txt.slice(0, 200) }; }
          } catch (e) { return { _err: e.message }; }
        }, { kw, offset }).catch(e => ({ _err: e.message }));

        const n = (payload && payload.data) ? payload.data.length : 0;
        if (n > 0) break;
        await sleep(rnd(2500, 4500));
      }

      const data = (payload && payload.data) || [];
      if (!data.length) {
        console.log(`  [${kw}] pg${pg + 1} 空 (${(payload && (payload._err || payload._raw)) || 'no data'})`);
        break;
      }

      for (const row of data) {
        const it = row.item;
        if (!it || !it.id || !it.stats) continue;
        const s = it.stats;
        const id = String(it.id);
        if (bag.has(id)) {
          bag.get(id).hits++;
          bag.get(id).kws.add(kw);
          continue;
        }
        bag.set(id, {
          id,
          kw,
          kws: new Set([kw]),
          hits: 1,
          desc: (it.desc || '').replace(/\s+/g, ' ').trim(),
          lang: it.textLanguage || '',
          author: (it.author && it.author.uniqueId) || '',
          nickname: (it.author && it.author.nickname) || '',
          followers: (it.authorStats && it.authorStats.followerCount) || 0,
          createTime: it.createTime || 0,
          play: Number(s.playCount) || 0,
          digg: Number(s.diggCount) || 0,
          comment: Number(s.commentCount) || 0,
          share: Number(s.shareCount) || 0,
          collect: Number(s.collectCount) || 0,
          isAd: !!it.isAd,
          aigc: it.aigcLabelType || 0,
          dur: (it.video && it.video.duration) || 0,
          music: (it.music && it.music.title) || '',
        });
        got++;
      }
      await sleep(rnd(1200, 2600));
    }
    kwStat.push({ kw, got });
    console.log(`  ${kw.padEnd(24)} ${got} 条`);
    await sleep(rnd(1500, 3000));
  }

  // 落地
  const arr = [...bag.values()].map(r => {
    const eng = r.play ? (r.digg + r.comment + r.share) / r.play : 0;
    return {
      ...r,
      kws: [...r.kws],
      eng: +eng.toFixed(4),
      hot: r.play >= 100000 ? 'HOT' : r.play >= 20000 ? 'MID' : 'LOW',
      date: r.createTime ? new Date(r.createTime * 1000).toISOString().slice(0, 10) : '',
    };
  }).sort((a, b) => b.play - a.play);

  fs.writeFileSync(OUT, JSON.stringify({ harvestedAt: new Date().toISOString(), kwStat, items: arr }, null, 2), 'utf-8');

  // ---- 控制台报告 ----
  console.log(`\n去重后 ${arr.length} 条  →  ${OUT}`);
  const hot = arr.filter(r => r.play >= 100000);
  const mid = arr.filter(r => r.play >= 20000 && r.play < 100000);
  console.log(`\n=== 播放档位分布 ===`);
  console.log(`10万+ ${hot.length} 条 | 2-10万 ${mid.length} 条 | 2万以下 ${arr.length - hot.length - mid.length} 条`);

  console.log(`\n=== TOP 25（按播放）===`);
  hot.slice(0, 25).forEach((r, i) => {
    console.log(`${String(i + 1).padStart(2)}. ${String(r.play).padStart(9)} 播放 | 赞${String(r.digg).padStart(6)} 评${String(r.comment).padStart(5)} 转${String(r.share).padStart(5)} | @${r.author.slice(0, 18)} (${r.followers}粉)`);
    console.log(`    ${r.desc.slice(0, 100)}`);
  });

  // 作者维度：谁在这些词下反复出爆款
  const byAuthor = new Map();
  arr.forEach(r => {
    if (!r.author) return;
    const a = byAuthor.get(r.author) || { author: r.author, nickname: r.nickname, followers: r.followers, n: 0, hot: 0, maxPlay: 0, total: 0 };
    a.n++; a.total += r.play; a.maxPlay = Math.max(a.maxPlay, r.play);
    if (r.play >= 100000) a.hot++;
    byAuthor.set(r.author, a);
  });
  const tops = [...byAuthor.values()].filter(a => a.hot > 0 || a.total > 200000)
    .sort((a, b) => b.hot - a.hot || b.total - a.total).slice(0, 15);
  console.log(`\n=== 高产账号 TOP ${tops.length} ===`);
  tops.forEach((a, i) => {
    console.log(`${String(i + 1).padStart(2)}. @${a.author.padEnd(22)} ${String(a.followers).padStart(8)}粉 | 命中${String(a.n).padStart(3)}条 爆款${String(a.hot).padStart(2)}条 | 最高${a.maxPlay} | 合计${a.total}`);
  });

  await browser.close();
  process.exit(0);
})().catch(e => { console.log('FATAL', e.message); process.exit(1); });
