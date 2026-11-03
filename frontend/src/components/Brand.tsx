const logoUrl = new URL('../assets/qingyou_logo.png', import.meta.url).href
const titleUrl = new URL('../assets/qingyou_title.png', import.meta.url).href

export function Brand({ subtitle = 'AI 生图', responsive = false }: { subtitle?: string; responsive?: boolean }) {
  return <span className={`brand-identity${responsive ? ' brand-responsive' : ''}`}>
    <span className="brand-title-image"><img src={titleUrl} alt="青柚" /></span>
    {responsive && <img className="brand-mobile-icon" src={logoUrl} alt="青柚" width={36} height={36} />}
    <span className="brand-subtitle">{subtitle}</span>
  </span>
}

export function BrandIcon() {
  return <img className="brand-icon" src={logoUrl} alt="青柚" width={48} height={48} />
}

export function BrandLoading() {
  return <div className="brand-loading" role="status"><BrandIcon /><span>青柚 · 加载中…</span></div>
}
