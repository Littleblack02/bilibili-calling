import type { Metadata } from "next";
import { ZCOOL_XiaoWei, Noto_Sans_SC } from "next/font/google";
import "./globals.css";

const display = ZCOOL_XiaoWei({
  subsets: ["latin"],
  weight: "400",
  variable: "--font-display",
});

const body = Noto_Sans_SC({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-body",
});

const socialImage = "https://raw.githubusercontent.com/Littleblack02/bilibili-calling/main/frontend/public/og.png";

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL || "https://littleblack02.github.io/bilibili-calling"),
  title: {
    default: "bilibili_calling · Ontology 智能推荐",
    template: "%s · bilibili_calling",
  },
  description: "可交互的 B站知识检索与个性化推荐 Demo：Ontology V2 实时概念计算、Grounded RAG 与强制 LLM 推荐链路。",
  openGraph: {
    title: "bilibili_calling · Ontology 智能推荐",
    description: "从个人知识库到可解释推荐：实时 Ontology 图计算与经过验证的 LLM 工具链路。",
    type: "website",
    locale: "zh_CN",
    images: [{ url: socialImage, width: 1680, height: 941, alt: "Ontology 驱动的视频推荐知识图谱" }],
  },
  twitter: {
    card: "summary_large_image",
    title: "bilibili_calling · Ontology 智能推荐",
    description: "实时 Ontology 图计算与经过验证的 LLM 推荐链路。",
    images: [socialImage],
  },
  icons: {
    icon: "/favicon.ico",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body className={`${display.variable} ${body.variable} antialiased`}>
        {children}
      </body>
    </html>
  );
}
