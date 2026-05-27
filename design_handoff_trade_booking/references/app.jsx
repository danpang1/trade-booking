// Main canvas wiring up all the sections.

const {
  Strengths, Gaps,
  ProposedBlotter,
  ProposedBookingDrawer,
  ApprovalQueue, AuditHistory, PositionView,
  DesignSystem,
} = window;

function App() {
  return (
    <DesignCanvas>
      <DCSection id="intro" title="Trade Booking UI · Institutional-grade Review" subtitle="Tokka Labs · Trade Management System — what's working, what to push, where to land">
        <DCArtboard id="strengths" label="A · Strengths" width={600} height={820}>
          <Strengths />
        </DCArtboard>
        <DCArtboard id="gaps" label="B · Gaps & opportunities" width={600} height={1260}>
          <Gaps />
        </DCArtboard>
      </DCSection>

      <DCSection id="blotter" title="01 · The Blotter, re-imagined" subtitle="Deal Enquiry as a real institutional blotter: dense rows, saved views, chip filters, KPI strip, footer aggregations, structured columns.">
        <DCArtboard id="blotter-proposed" label="Proposed · Deal Enquiry" width={1920} height={1180}>
          <ProposedBlotter />
        </DCArtboard>
      </DCSection>

      <DCSection id="booking" title="02 · Booking as a contextual drawer" subtitle="Drawer over the blotter · inline validation · structured summary · live JSON pane gets the room it deserves.">
        <DCArtboard id="booking-proposed" label="Proposed · Spot booking drawer" width={1920} height={1220}>
          <ProposedBookingDrawer />
        </DCArtboard>
      </DCSection>

      <DCSection id="workflow" title="03 · Pending Bookings, redesigned" subtitle="The queue and the audit trail — both already exist in your system, just need real surface.">
        <DCArtboard id="approvals" label="A · Pending bookings · queue view" width={760} height={900}>
          <ApprovalQueue />
        </DCArtboard>
        <DCArtboard id="audit" label="B · Audit trail peek" width={580} height={900}>
          <AuditHistory />
        </DCArtboard>
      </DCSection>

      <DCSection id="system" title="04 · The design system underneath" subtitle="Two-family type, paper + ink + signals, dense row grid, status pills, keyboard surface.">
        <DCArtboard id="ds" label="System shelf" width={1920} height={1180}>
          <DesignSystem />
        </DCArtboard>
      </DCSection>
    </DesignCanvas>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
