export default function SourcesToggleButton({ onClick, title }: { onClick: () => void; title: string }) {
  return (
    <button
      onClick={onClick}
      className="sources-toggle-btn"
      title={title}
      style={{
        width: '48px',
        height: '48px',
        borderRadius: '50%',
        backgroundColor: '#ff9ec4',
        border: 'none',
        cursor: 'pointer',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 0,
        transition: 'transform 0.15s ease',
      }}
      onMouseEnter={(e) => e.currentTarget.style.transform = 'scale(1.05)'}
      onMouseLeave={(e) => e.currentTarget.style.transform = 'scale(1)'}
    >
      <svg
        width="28"
        height="28"
        viewBox="0 0 28 28"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        {/* 电视主体外轮廓 */}
        <rect
          x="2"
          y="5"
          width="24"
          height="17"
          rx="3"
          fill="white"
        />

        {/* 电视屏幕（挖空） */}
        <rect
          x="4"
          y="7"
          width="20"
          height="13"
          rx="2"
          fill="#ff9ec4"
        />

        {/* 左天线 */}
        <path
          d="M6 5 L4 2"
          stroke="white"
          strokeWidth="2"
          strokeLinecap="round"
        />

        {/* 右天线 */}
        <path
          d="M22 5 L24 2"
          stroke="white"
          strokeWidth="2"
          strokeLinecap="round"
        />

        {/* 左脚 */}
        <rect
          x="6"
          y="22"
          width="3"
          height="2"
          rx="1"
          fill="white"
        />

        {/* 右脚 */}
        <rect
          x="19"
          y="22"
          width="3"
          height="2"
          rx="1"
          fill="white"
        />

        {/* 右侧凸起 */}
        <rect
          x="26"
          y="11"
          width="1.5"
          height="3"
          rx="0.75"
          fill="white"
        />

        {/* 左眉眼（倾斜的短圆角矩形） */}
        <rect
          x="8"
          y="10"
          width="3"
          height="2"
          rx="1"
          fill="white"
          transform="rotate(-15, 9.5, 11)"
        />

        {/* 右眉眼 */}
        <rect
          x="17"
          y="10"
          width="3"
          height="2"
          rx="1"
          fill="white"
          transform="rotate(15, 18.5, 11)"
        />

        {/* 嘴巴（波浪形） */}
        <path
          d="M11 15 Q12.5 16, 14 15 Q15.5 16, 17 15"
          stroke="white"
          strokeWidth="1.5"
          strokeLinecap="round"
          fill="none"
        />
      </svg>
    </button>
  );
}
