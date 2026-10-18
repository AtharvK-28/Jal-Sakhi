// Indicative single-unit retail prices (INR) for a prototype build. Not quotations and not a tender
// estimate: they exist so the cost of a sensing layout can be compared, not budgeted.

export const PART = {
  mcu: 450, pressure: 650, flow: 350, turbidity: 850, tds: 550, ph: 1400, uplink: 450, power: 600, enclosure: 550,
  tankLevel: 800, pumpMonitor: 1500, boreLevel: 3500, bulkFlow: 4500,
};

export const BOM: [string, string, number][] = [
  ["ESP32-WROOM-32 dev board", "MCU, Wi-Fi + BLE; deep-sleep between reports", PART.mcu],
  ["Pressure transducer 0 to 1.2 MPa, 0.5 to 4.5 V (G1/4)", "Lane entry / tail / tap pressure", PART.pressure],
  ["YF-S201 / YF-B5 hall-effect flow sensor", "Lane or household flow, pulse output", PART.flow],
  ["Analog turbidity sensor (TSW-30 class)", "Turbidity screening at tank outlet / tail", PART.turbidity],
  ["TDS probe + signal board", "Dissolved solids screening", PART.tds],
  ["pH probe + signal board (quality nodes only)", "pH screening; needs monthly calibration", PART.ph],
  ["SIM800L GSM or RA-02 LoRa module", "Uplink where there is no Wi-Fi", PART.uplink],
  ["6 V 3 W solar panel + TP4056 + 18650 cell", "Autonomous power, about 5 days without sun", PART.power],
  ["IP65 enclosure, glands, fittings, PCB", "Weatherproofing and mounting", PART.enclosure],
  ["Ultrasonic level sensor", "Tank level", PART.tankLevel],
  ["Current clamp + vibration sensor", "Pump condition", PART.pumpMonitor],
  ["Submersible level probe", "Borewell water level", PART.boreLevel],
  ["Bulk flow meter, pulse output", "Main outlet flow", PART.bulkFlow],
];

const base = PART.mcu + PART.uplink + PART.power + PART.enclosure; // what every node carries
export const NODE = {
  tap: base + PART.pressure + PART.flow,
  laneEntry: base + PART.pressure + PART.flow,
  laneTail: base + PART.pressure,
  quality: base + PART.turbidity + PART.tds + PART.ph,
  tank: base + PART.tankLevel,
  pump: base + PART.pumpMonitor,
  source: base + PART.boreLevel,
  main: base + PART.bulkFlow,
};

/** Hardware for one village scheme: metered taps, a sensor pair on every lane, and the scheme-level nodes. */
export function villageHardware(tapsPerLane: number | "all", lanes = 5, homes = 100): number {
  const taps = tapsPerLane === "all" ? homes : tapsPerLane * lanes;
  return taps * NODE.tap + lanes * (NODE.laneEntry + NODE.laneTail) + NODE.tank + NODE.pump + NODE.source + NODE.main + 2 * NODE.quality;
}

// Running-cost assumptions, stated so they can be argued with.
export const YEARS_OF_LIFE = 5; // hardware written off over five years
export const UPKEEP_SHARE = 0.12; // probes, calibration, replacements and visits: 12% of hardware a year
export const CONNECTIVITY_PER_VILLAGE = 1500; // one gateway SIM a year

/** Indicative cost per household per year for a sensing layout. */
export function yearlyPerHome(hardware: number, homes = 100): number {
  return (hardware / YEARS_OF_LIFE + hardware * UPKEEP_SHARE + CONNECTIVITY_PER_VILLAGE) / homes;
}
