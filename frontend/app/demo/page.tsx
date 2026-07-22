import type { Metadata } from "next";
import InterviewDemo from "@/components/InterviewDemo";

export const metadata: Metadata = {
  title: "交互 Demo | bilibili_calling",
  description: "无需登录，体验 Ontology 用户画像、Grounded RAG 与可解释推荐闭环。",
};

export default function DemoPage() {
  return <InterviewDemo />;
}
