import { BriefingSection } from "@/components/BriefingSection";
import { FieldPoster } from "@/components/FieldPoster";
import { Header } from "@/components/Header";
import { Hero } from "@/components/Hero";
import { MotionRoot } from "@/components/MotionRoot";
import { PipelineSection } from "@/components/PipelineSection";
import { ScorecardSection } from "@/components/ScorecardSection";
import { FaqSection, Footer, MethodSection, ProvenanceSection, ReliabilitySection } from "@/components/Sections";
import { SignalField } from "@/components/SignalField";
import { Ticker } from "@/components/Ticker";
import { demo } from "@/lib/demo";

export default function Home() {
  return (
    <>
      <a
        href="#main"
        className="sr-only z-50 bg-paper px-4 py-2 text-carbon focus:not-sr-only focus:fixed focus:left-4 focus:top-4"
      >
        Skip to content
      </a>
      <SignalField
        traces={demo.traces}
        session={demo.pipeline.arrivals[0]?.session ?? ""}
        poster={<FieldPoster />}
      />
      <Header />
      <Ticker />
      <main id="main">
        <Hero />
        <BriefingSection />
        <PipelineSection />
        <MethodSection />
        <ProvenanceSection />
        <ScorecardSection />
        <ReliabilitySection />
        <FaqSection />
      </main>
      <Footer />
      <MotionRoot />
    </>
  );
}
