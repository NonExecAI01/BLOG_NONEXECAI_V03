/**
 * iframe-embed.js — Non-Exec AI Blog
 * ─────────────────────────────────────────────────────────────────────────────
 * Drop this script on any parent page where you want to embed the blog as a
 * responsive, auto-height iframe.
 *
 * Usage on your main site (www.non-exec.ai):
 *   1. Add a container element where you want the blog to appear:
 *        <div id="nonexecai-blog"></div>
 *
 *   2. Load this script (anywhere, defer-safe):
 *        <script src="https://<your-blog-domain>/iframe-embed.js" defer></script>
 *
 *   The script will:
 *     • Inject a <iframe> into #nonexecai-blog (or a fallback <div>)
 *     • Listen for postMessage events from the iframe
 *     • Resize the iframe height automatically as content changes
 *     • Handle window resize / orientation changes
 * ─────────────────────────────────────────────────────────────────────────────
 */

(function () {
  'use strict';

  /* ── Configuration ──────────────────────────────────────────────────────── */
  var CONFIG = {
    // URL of the blog page to embed
    blogUrl: 'https://nonexecai01.github.io/BLOG_NONEXECAI_V03/',

    // CSS selector for the host container (falls back to body append)
    containerId: 'nonexecai-blog',

    // Minimum iframe height before the first message arrives
    minHeight: 600,

    // Transition for smooth height animations
    transition: 'height 0.25s ease',

    // postMessage type identifier (must match the value in index.html)
    messageType: 'nonexecai-resize',
  };

  /* ── Helpers ────────────────────────────────────────────────────────────── */
  function log(msg) {
    if (window.console && window.console.log) {
      console.log('[NonExecAI Embed] ' + msg);
    }
  }

  function getContainer() {
    var el = document.getElementById(CONFIG.containerId);
    if (!el) {
      log('Container #' + CONFIG.containerId + ' not found — appending to <body>.');
      el = document.createElement('div');
      el.id = CONFIG.containerId;
      document.body.appendChild(el);
    }
    return el;
  }

  /* ── Build the iframe ───────────────────────────────────────────────────── */
  function buildIframe(container) {
    var iframe = document.createElement('iframe');

    iframe.src             = CONFIG.blogUrl;
    iframe.id              = 'nonexecai-blog-iframe';
    iframe.title           = 'Non-Exec AI Corporate Governance Insights';
    iframe.allowFullscreen = false;
    iframe.loading         = 'lazy';   // native lazy load
    iframe.scrolling       = 'no';     // hide scroll bar; height matches content

    /* Accessible landmark */
    iframe.setAttribute('aria-label', 'Non-Exec AI Blog');

    /* Inline styles — kept minimal; override in your own CSS via #nonexecai-blog-iframe */
    iframe.style.cssText = [
      'display: block',
      'width: 100%',
      'border: none',
      'height: ' + CONFIG.minHeight + 'px',
      'transition: ' + CONFIG.transition,
      'overflow: hidden',
    ].join('; ');

    container.appendChild(iframe);
    log('iframe injected → ' + CONFIG.blogUrl);
    return iframe;
  }

  /* ── postMessage listener ───────────────────────────────────────────────── */
  function attachMessageListener(iframe) {
    window.addEventListener('message', function (event) {
      // Security: only accept messages from the iframe's origin
      var iframeSrc;
      try {
        iframeSrc = new URL(CONFIG.blogUrl).origin;
      } catch (e) {
        iframeSrc = null;
      }

      // Allow same-origin or matching origin; skip mismatched origins
      if (iframeSrc && event.origin !== iframeSrc && event.origin !== window.location.origin) {
        return;
      }

      var data = event.data;

      // Support both raw number (legacy) and object with type field
      if (typeof data === 'number') {
        setHeight(iframe, data);
        return;
      }

      if (
        data &&
        typeof data === 'object' &&
        data.type === CONFIG.messageType &&
        typeof data.height === 'number'
      ) {
        setHeight(iframe, data.height);
      }
    });

    log('postMessage listener attached.');
  }

  /* ── Apply height ───────────────────────────────────────────────────────── */
  function setHeight(iframe, height) {
    var safeHeight = Math.max(height, CONFIG.minHeight);
    if (parseInt(iframe.style.height, 10) !== safeHeight) {
      iframe.style.height = safeHeight + 'px';
    }
  }

  /* ── Fallback: poll iframe document height (same-origin only) ───────────── */
  function pollHeight(iframe) {
    var last = 0;
    setInterval(function () {
      try {
        var doc = iframe.contentDocument || iframe.contentWindow.document;
        var h   = doc.documentElement.scrollHeight || doc.body.scrollHeight;
        if (h && h !== last) {
          last = h;
          setHeight(iframe, h);
        }
      } catch (e) {
        // Cross-origin: silently ignore; postMessage is the primary mechanism
      }
    }, 500);
  }

  /* ── Debounced window resize ────────────────────────────────────────────── */
  function onWindowResize(iframe) {
    var timer;
    window.addEventListener('resize', function () {
      clearTimeout(timer);
      timer = setTimeout(function () {
        // Re-request height from iframe after layout reflow
        try {
          if (iframe.contentWindow) {
            iframe.contentWindow.postMessage({ type: 'nonexecai-request-height' }, '*');
          }
        } catch (e) { /* cross-origin guard */ }
      }, 150);
    });
  }

  /* ── Init ───────────────────────────────────────────────────────────────── */
  function init() {
    var container = getContainer();
    var iframe    = buildIframe(container);
    attachMessageListener(iframe);
    pollHeight(iframe);      // same-origin fallback
    onWindowResize(iframe);
  }

  /* ── DOM ready guard ────────────────────────────────────────────────────── */
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  /* ── Public API (optional, accessible via window.NonExecAIEmbed) ─────────── */
  window.NonExecAIEmbed = {
    config: CONFIG,
    reinit: init,
  };

})();
