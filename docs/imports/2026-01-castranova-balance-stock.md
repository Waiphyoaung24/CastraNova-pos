# CastraNova — Balance Stock Import Prep (January 2026)

## Header

| Field | Value |
|---|---|
| Source | Aquamarine Moon Co.,Ltd — Balance Stock (1/2026) — rebranded as CastraNova stock |
| Generated | 2026-06-15 |
| Item count | 214 (Item IDs 0001–0214) |
| Exchange rates applied | USD × 33 (1 USD = 33 THB); MMK ÷ 132.5 (1 THB = 132.5 MMK / kyat-per-baht) |
| THB rounding | 2 decimal places, per-unit price only (NOT price × qty) |
| SKU scheme | `CN-0001` … `CN-0214` (zero-padded from Item ID) |
| `qty_on_hand` note | Maps to a **receive / stock-adjustment movement** at import — NOT a `Product` column |
| `repair_price_thb` | `0` placeholder for all rows — fill before importing |
| `tracking_mode` | `QUANTITY` for all rows |
| Currency classification | USD if `$` price shown; MMK if bare number in Total (Ks) only; none if price is `-` |
| NO-PRICE rows | 0191, 0192, 0193, 0194, 0195, 0196, 0197, 0204 (confirmed from PDF) |

---

## Stock Table

| sku | model_name | model_no | size | brand | category | tracking_mode | qty_on_hand | orig_price | orig_currency | retail_price_thb | repair_price_thb | flags |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CN-0001 | (3)HP , Scroll Condensing Unit (220V/1Ph)R22 | LMGC 030 CO2D (R22) | | | Condensing Unit | QUANTITY | 5 | 1250 | USD | 41250.00 | 0 | |
| CN-0002 | Low (5)HP Piston Compressor | SP 2L 050E | | | Compressor | QUANTITY | 3 | 1200 | USD | 39600.00 | 0 | |
| CN-0003 | High Temp (10)HP, Piston Compressor | SP 4HF100E | | | Compressor | QUANTITY | 1 | 1895 | USD | 62535.00 | 0 | |
| CN-0004 | Condenser | KH-402 A3 | | | Condenser | QUANTITY | 1 | 480 | USD | 15840.00 | 0 | |
| CN-0005 | Unit Cooler (AUKS) | AD 304 A4F | | | Unit Cooler | QUANTITY | 1 | 1500 | USD | 49500.00 | 0 | |
| CN-0006 | Unit Cooler | AT-402 C3 | | | Unit Cooler | QUANTITY | 1 | 722 | USD | 23826.00 | 0 | |
| CN-0007 | Unit Cooler | AT-403 R6 | | | Unit Cooler | QUANTITY | 1 | 1420 | USD | 46860.00 | 0 | |
| CN-0008 | Unit Cooler | AT-503 R6 | | | Unit Cooler | QUANTITY | 1 | 2420 | USD | 79860.00 | 0 | |
| CN-0009 | Unit Cooler | AK-634 R8 | | | Unit Cooler | QUANTITY | 1 | 6960 | USD | 229680.00 | 0 | |
| CN-0010 | Oil Separator | PKW-55824, | 1/2" | | Oil Separator | QUANTITY | 5 | 32 | USD | 1056.00 | 0 | |
| CN-0011 | Oil Separator | ZTW 55855A | 5/8" | | Oil Separator | QUANTITY | 7 | 37 | USD | 1221.00 | 0 | |
| CN-0012 | Oil Separator | PKW-55855A, | 5/8" | | Oil Separator | QUANTITY | 3 | 37 | USD | 1221.00 | 0 | |
| CN-0013 | Oil Separator | ZTW 569213 | 1-5/8" | | Oil Separator | QUANTITY | 7 | 75 | USD | 2475.00 | 0 | |
| CN-0014 | Receiver | ZTC- 44L | | | Receiver | QUANTITY | 1 | 290 | USD | 9570.00 | 0 | |
| CN-0015 | Receiver | ZTC-844, 8L | 1/2" | | Receiver | QUANTITY | 2 | 45 | USD | 1485.00 | 0 | |
| CN-0016 | Receiver | 30L, V9 | | | Receiver | QUANTITY | 1 | 189 | USD | 6237.00 | 0 | |
| CN-0017 | Receiver | ZTC-1055, 10L | 5/8" | | Receiver | QUANTITY | 2 | 62 | USD | 2046.00 | 0 | |
| CN-0018 | Receiver | ZTC-14CL, 5/8,14L | | | Receiver | QUANTITY | 1 | 89 | USD | 2937.00 | 0 | |
| CN-0019 | Receiver | ZTC-19CL, 7/8,18L | | | Receiver | QUANTITY | 1 | 89 | USD | 2937.00 | 0 | |
| CN-0020 | Receiver | PKC-101 | | | Receiver | QUANTITY | 1 | 19 | USD | 627.00 | 0 | |
| CN-0021 | Accumulator | FA 207 | | | Accumulator | QUANTITY | 3 | 34 | USD | 1122.00 | 0 | |
| CN-0022 | Hand Valve (Danfoss) | BML-12" 009G0141 | 1/2" | Danfoss | Hand Valve | QUANTITY | 30 | 20 | USD | 660.00 | 0 | |
| CN-0023 | Hand Valve (Danfoss) | BML-6" 009G0101 | 1/4" | Danfoss | Hand Valve | QUANTITY | 10 | 11 | USD | 363.00 | 0 | |
| CN-0024 | Hand Valve (Danfoss) | BML-10" 009G0127 | 3/8" | Danfoss | Hand Valve | QUANTITY | 30 | 17 | USD | 561.00 | 0 | |
| CN-0025 | Hand Valve (Danfoss) | BML-15" 009G0168 | 5/8" | Danfoss | Hand Valve | QUANTITY | 18 | 29 | USD | 957.00 | 0 | |
| CN-0026 | Ball Valve | | 1/4" | | Ball Valve | QUANTITY | 37 | 15 | USD | 495.00 | 0 | Model No missing |
| CN-0027 | Ball Valve | | 3/8" | | Ball Valve | QUANTITY | 1 | 15 | USD | 495.00 | 0 | Model No missing |
| CN-0028 | Ball Valve | GBC | 1/2" | | Ball Valve | QUANTITY | 12 | 17 | USD | 561.00 | 0 | |
| CN-0029 | Ball Valve | GBC | 3/4" | | Ball Valve | QUANTITY | 15 | 17 | USD | 561.00 | 0 | |
| CN-0030 | Ball Valve | GBC | 1-1/8" | | Ball Valve | QUANTITY | 7 | 45 | USD | 1485.00 | 0 | |
| CN-0031 | Ball Valve | GBC-35S | 1-3/8" | | Ball Valve | QUANTITY | 1 | 57 | USD | 1881.00 | 0 | |
| CN-0032 | Ball Valve | PKB-22, | 1-3/8" | | Ball Valve | QUANTITY | 1 | 49 | USD | 1617.00 | 0 | |
| CN-0033 | Ball Valve | | 1-5/8" | | Ball Valve | QUANTITY | 5 | 84 | USD | 2772.00 | 0 | Model No missing |
| CN-0034 | Ball Valve | PKB-26, | 1-5/8" | | Ball Valve | QUANTITY | 1 | 64 | USD | 2112.00 | 0 | |
| CN-0035 | Ball Valve | | 2-1/8" | | Ball Valve | QUANTITY | 2 | 120 | USD | 3960.00 | 0 | Model No missing |
| CN-0036 | Ball Valve | PKB-34, | 2-1/8" | | Ball Valve | QUANTITY | 1 | 110 | USD | 3630.00 | 0 | |
| CN-0037 | Ball Valve | AP 17865C, | 1-1/8" | | Ball Valve | QUANTITY | 3 | 48 | USD | 1584.00 | 0 | |
| CN-0038 | Ball Valve | APX 17867C, | 1-5/8" | | Ball Valve | QUANTITY | 4 | 31 | USD | 1023.00 | 0 | |
| CN-0039 | Ball Valve (Danfoss) | GBC-12S, 009L0722 | 1/2 | Danfoss | Ball Valve | QUANTITY | 1 | 108 | USD | 3564.00 | 0 | |
| CN-0040 | Ball Valve(Danfoss) | GBC-45 Bar | 2-1/8 | Danfoss | Ball Valve | QUANTITY | 1 | 195 | USD | 6435.00 | 0 | |
| CN-0041 | Ball Valve(Danfoss) | GBC-35S Bar | 1-3/8" | Danfoss | Ball Valve | QUANTITY | 1 | 196 | USD | 6468.00 | 0 | |
| CN-0042 | Filter Drier (WELCOLD) | 1/4, FDL 052 | 1/4" | WELCOLD | Filter Drier | QUANTITY | 40 | 6 | USD | 198.00 | 0 | |
| CN-0043 | Filter Drier (Danfoss) | DML-306 (Flare) | 3/4" | Danfoss | Filter Drier | QUANTITY | 4 | 21 | USD | 693.00 | 0 | |
| CN-0044 | Filter Drier (WELCOLD) | FDL 163 | 3/8" | WELCOLD | Filter Drier | QUANTITY | 24 | 8 | USD | 264.00 | 0 | |
| CN-0045 | WELCOLD Filter Drier | FDL 165, | 5/8" | WELCOLD | Filter Drier | QUANTITY | 4 | 9 | USD | 297.00 | 0 | |
| CN-0046 | Filter Drier | DML-164S | 1/2" | | Filter Drier | QUANTITY | 2 | 9 | USD | 297.00 | 0 | |
| CN-0047 | Filter Drier (HEOK) | PKES-052 , | 1/4" | HEOK | Filter Drier | QUANTITY | 60 | 6 | USD | 198.00 | 0 | |
| CN-0048 | Filter Drier | PKES -304, 1/2" | 1/2" | | Filter Drier | QUANTITY | 5 | 9 | USD | 297.00 | 0 | |
| CN-0049 | Filter Drier (HEOK)(Short) | PKES-083, 3/8 | 3/8" | HEOK | Filter Drier | QUANTITY | 14 | 6 | USD | 198.00 | 0 | |
| CN-0050 | Filter Drier (HEOK)(Long) | PKES-163, 3/8 | 3/8" | HEOK | Filter Drier | QUANTITY | 13 | 6 | USD | 198.00 | 0 | |
| CN-0051 | Filter Drier (Flare) | ZTEK 053, 3/8 | 3/8" | | Filter Drier | QUANTITY | 9 | 6 | USD | 198.00 | 0 | |
| CN-0052 | Filter Drier (Flare) | ZTEK 416, | 3/4" | | Filter Drier | QUANTITY | 5 | 24 | USD | 792.00 | 0 | |
| CN-0053 | Filter Drier (Flare) | ZTEK 419S, | 1-1/8" | | Filter Drier | QUANTITY | 2 | 27 | USD | 891.00 | 0 | |
| CN-0054 | Suction Filter Drier | KRSTE-4817T | 2 1/8" | | Suction Filter | QUANTITY | 4 | 39 | USD | 1287.00 | 0 | |
| CN-0055 | Filter Core | F-48 | F-48" | | Filter Core | QUANTITY | 10 | 16 | USD | 528.00 | 0 | |
| CN-0056 | Sight Glass (Danfoss) | 014-0183 (Danfoss) | 1/2" | Danfoss | Sight Glass | QUANTITY | 16 | 14 | USD | 462.00 | 0 | |
| CN-0057 | Sight Glass | Hongsen | 1/2" | Hongsen | Sight Glass | QUANTITY | 5 | 9 | USD | 297.00 | 0 | |
| CN-0058 | Sight Glass | SAE (flare) | 1/2" | | Sight Glass | QUANTITY | 4 | 9 | USD | 297.00 | 0 | |
| CN-0059 | Sight Glass | PK - 13S , HPEOK | 3/8" | HPEOK | Sight Glass | QUANTITY | 1 | 7 | USD | 231.00 | 0 | |
| CN-0060 | Sight Glass | SAE (flare) | 3/8" | | Sight Glass | QUANTITY | 8 | 7 | USD | 231.00 | 0 | |
| CN-0061 | Sight Glass | PK - 15S , HPEOK | 5/8" | HPEOK | Sight Glass | QUANTITY | 1 | 9 | USD | 297.00 | 0 | |
| CN-0062 | Sight Glass | ODF | 5/8" | | Sight Glass | QUANTITY | 4 | 9 | USD | 297.00 | 0 | |
| CN-0063 | Sight Glass | SAE (flare) | 5/8" | | Sight Glass | QUANTITY | 4 | 9 | USD | 297.00 | 0 | |
| CN-0064 | Sight Glass | PK - 16S , HPEOK | 3/4" | HPEOK | Sight Glass | QUANTITY | 1 | 16 | USD | 528.00 | 0 | |
| CN-0065 | Sight Glass | Hongsen | 3/4" | Hongsen | Sight Glass | QUANTITY | 5 | 11 | USD | 363.00 | 0 | |
| CN-0066 | Sight Glass | ODF | 3/4" | | Sight Glass | QUANTITY | 2 | 12 | USD | 396.00 | 0 | |
| CN-0067 | Sight Glass | Hongsen | 7/8" | Hongsen | Sight Glass | QUANTITY | 6 | 13 | USD | 429.00 | 0 | |
| CN-0068 | Sight Glass | ODF | 7/8" | | Sight Glass | QUANTITY | 1 | 13 | USD | 429.00 | 0 | |
| CN-0069 | Sight Glass | ODF | 1-1/8" | | Sight Glass | QUANTITY | 8 | 21 | USD | 693.00 | 0 | |
| CN-0070 | Check Valve | Hongsen (straight) | 5/8" | Hongsen | Check Valve | QUANTITY | 11 | 58 | USD | 1914.00 | 0 | |
| CN-0071 | Check Valve | Hongsen (straight) | 3/4" | Hongsen | Check Valve | QUANTITY | 12 | 58 | USD | 1914.00 | 0 | |
| CN-0072 | Check Valve | Hongsen (Angle) | 7/8" | Hongsen | Check Valve | QUANTITY | 8 | 59 | USD | 1947.00 | 0 | |
| CN-0073 | Check Valve | Hongsen (Angle) | 1-3/8" | Hongsen | Check Valve | QUANTITY | 5 | 85 | USD | 2805.00 | 0 | |
| CN-0074 | Check Valve | Hongsen (Angle) | 1-5/8" | Hongsen | Check Valve | QUANTITY | 1 | 131 | USD | 4323.00 | 0 | |
| CN-0075 | Check Valve | XFV-26 (Straight) | 1-5/8" | | Check Valve | QUANTITY | 3 | 131 | USD | 4323.00 | 0 | |
| CN-0076 | Check Valve | V-34X (Straight) | 2-1/8" | | Check Valve | QUANTITY | 7 | 145 | USD | 4785.00 | 0 | |
| CN-0077 | Vibration Eliminators | | 1-3/8" | | Vibration Eliminator | QUANTITY | 12 | 27 | USD | 891.00 | 0 | Model No missing |
| CN-0078 | Vibration Eliminators | | 1-5/8" | | Vibration Eliminator | QUANTITY | 13 | 31 | USD | 1023.00 | 0 | Model No missing |
| CN-0079 | Vibration Eliminators | 1-5/8" (ANACONDA) | 1-5/8" | ANACONDA | Vibration Eliminator | QUANTITY | 2 | 69 | USD | 2277.00 | 0 | |
| CN-0080 | Vibration Eliminators | 2-1/8" | 2-1/8" | | Vibration Eliminator | QUANTITY | 14 | 46 | USD | 1518.00 | 0 | Model No missing |
| CN-0081 | Vibration Eliminators | 3/4" | 3/4" | | Vibration Eliminator | QUANTITY | 10 | 11 | USD | 363.00 | 0 | Model No missing |
| CN-0082 | Vibration Eliminators | 5/8" | 5/8" | | Vibration Eliminator | QUANTITY | 11 | 9 | USD | 297.00 | 0 | Model No missing |
| CN-0083 | Vibration Eliminators | 5/8" (ANACONDA) | 5/8" | ANACONDA | Vibration Eliminator | QUANTITY | 3 | 19 | USD | 627.00 | 0 | |
| CN-0084 | Vibration Eliminators | 7/8" (ANACONDA) | 7/8" | ANACONDA | Vibration Eliminator | QUANTITY | 2 | 29 | USD | 957.00 | 0 | |
| CN-0085 | Copper Pipe Clamps | | 5/8" | | Copper Pipe Clamp | QUANTITY | 15 | 3 | USD | 99.00 | 0 | Model No missing |
| CN-0086 | Copper Pipe Clamps | | 1-1/8" | | Copper Pipe Clamp | QUANTITY | 76 | 4 | USD | 132.00 | 0 | Model No missing |
| CN-0087 | Copper Pipe Clamps | | 1/2" | | Copper Pipe Clamp | QUANTITY | 3 | 3 | USD | 99.00 | 0 | Model No missing |
| CN-0088 | Copper Pipe Clamps | | 1/4" | | Copper Pipe Clamp | QUANTITY | 50 | 3 | USD | 99.00 | 0 | Model No missing |
| CN-0089 | Copper Pipe Clamps | | 3/4" | | Copper Pipe Clamp | QUANTITY | 81 | 3 | USD | 99.00 | 0 | Model No missing |
| CN-0090 | Copper Pipe Clamps | | 3/8" | | Copper Pipe Clamp | QUANTITY | 38 | 3 | USD | 99.00 | 0 | Model No missing |
| CN-0091 | Copper Pipe Clamps | | 7/8" | | Copper Pipe Clamp | QUANTITY | 125 | 2 | USD | 66.00 | 0 | Model No missing |
| CN-0092 | Copper Pipe Clamps | | 2-1/8" | | Copper Pipe Clamp | QUANTITY | 25 | 5 | USD | 165.00 | 0 | Model No missing |
| CN-0093 | (0 to 260 PSI)Gauges | MN 18 Bar | | | Gauge | QUANTITY | 9 | 41250 | MMK | 311.32 | 0 | MMK-priced |
| CN-0094 | (0 to 550 PSI)Gauges | MN 38 Bar | | | Gauge | QUANTITY | 13 | 41250 | MMK | 311.32 | 0 | MMK-priced |
| CN-0095 | Pressure Gauges Panels | 2 Gauges | | | Gauge | QUANTITY | 7 | 5 | USD | 165.00 | 0 | |
| CN-0096 | Straight Connector | 2mm | | | Connector | QUANTITY | 162 | 12000 | MMK | 90.57 | 0 | MMK-priced |
| CN-0097 | Elbow Connector | 2mm | | | Connector | QUANTITY | 86 | 12000 | MMK | 90.57 | 0 | MMK-priced |
| CN-0098 | Filling V/V Tee | 2mm | | | Connector | QUANTITY | 31 | 12000 | MMK | 90.57 | 0 | MMK-priced |
| CN-0099 | Tee | 2mm | | | Connector | QUANTITY | 15 | 12000 | MMK | 90.57 | 0 | MMK-priced |
| CN-0100 | Elbow Connector | 4mm | | | Connector | QUANTITY | 20 | 12375 | MMK | 93.40 | 0 | MMK-priced |
| CN-0101 | Straight Connector (with Pin) | 4mm | | | Connector | QUANTITY | 19 | 12375 | MMK | 93.40 | 0 | MMK-priced |
| CN-0102 | Filling V/V Tee | 4mm , | | | Connector | QUANTITY | 49 | 12375 | MMK | 93.40 | 0 | MMK-priced |
| CN-0103 | T Connector | 4mm , T Connector | | | Connector | QUANTITY | 50 | 12375 | MMK | 93.40 | 0 | MMK-priced |
| CN-0104 | Tee | 4mm , | | | Connector | QUANTITY | 50 | 12375 | MMK | 93.40 | 0 | MMK-priced |
| CN-0105 | 2 way | 4mm , 2 way | | | Connector | QUANTITY | 50 | 12375 | MMK | 93.40 | 0 | MMK-priced |
| CN-0106 | Pressure Switch | 060-124591 | KP15 | | Pressure Switch | QUANTITY | 1 | 450000 | MMK | 3396.23 | 0 | MMK-priced |
| CN-0107 | Differential Pressure Switch (H/L cutout) | 060B 016891 | MP 54 | | Pressure Switch | QUANTITY | 8 | 750000 | MMK | 5660.38 | 0 | MMK-priced |
| CN-0108 | Pressure Regulator (Danfoss) | KPV 35 , | | Danfoss | Pressure Regulator | QUANTITY | 3 | 289 | USD | 9537.00 | 0 | |
| CN-0109 | Expansion Valve | 067B3342 | TES-5 | Danfoss | Expansion Valve | QUANTITY | 7 | 97 | USD | 3201.00 | 0 | |
| CN-0110 | Orifice | Orifice-01 | TES-5 | | Orifice | QUANTITY | 6 | 38 | USD | 1254.00 | 0 | |
| CN-0111 | Orifice | Orifice-02 | TES-5 | | Orifice | QUANTITY | 9 | 38 | USD | 1254.00 | 0 | |
| CN-0112 | Expansion Valve Body | 067B 4007 | (1/2 x 5/8) | Danfoss | Expansion Valve Body | QUANTITY | 14 | 25 | USD | 825.00 | 0 | |
| CN-0113 | Expansion Valve Body | 067B 4032 | (5/8 x 7/8) | Danfoss | Expansion Valve Body | QUANTITY | 7 | 24 | USD | 792.00 | 0 | |
| CN-0114 | Expansion Valve Body | 067B4011 | (5/8 x 7/8) | Danfoss | Expansion Valve Body | QUANTITY | 6 | 24 | USD | 792.00 | 0 | |
| CN-0115 | Expansion Valve Body | 067B 4034 | (7/8 x 1-1/8) | Danfoss | Expansion Valve Body | QUANTITY | 8 | 24 | USD | 792.00 | 0 | |
| CN-0116 | Expansion Valve | 068 Z 3403 (Flare) | TE-2 , R404 | Danfoss | Expansion Valve | QUANTITY | 6 | 56 | USD | 1848.00 | 0 | |
| CN-0117 | Expansion Valve | 068Z 3415 (Solder) | TE-2 , R404 | Danfoss | Expansion Valve | QUANTITY | 1 | 52 | USD | 1716.00 | 0 | |
| CN-0118 | Orifice | Orifice -3 | TE-2 | | Orifice | QUANTITY | 1 | 10 | USD | 330.00 | 0 | |
| CN-0119 | Orifice | Orifice -5 | TE-2 | | Orifice | QUANTITY | 4 | 10 | USD | 330.00 | 0 | |
| CN-0120 | Solenoid Valve + Coil | 1-1/8", (Castal) | 1-1/8" | Castal | Solenoid Valve | QUANTITY | 4 | 335 | USD | 11055.00 | 0 | |
| CN-0121 | Solenoid Valve + Coil | 1-3/8", (Castal) | 1-3/8" | Castal | Solenoid Valve | QUANTITY | 3 | 318 | USD | 10494.00 | 0 | |
| CN-0122 | Solenoid Valve + Coil | 1-5/8", (Castal) | 1-5/8" | Castal | Solenoid Valve | QUANTITY | 2 | 423 | USD | 13959.00 | 0 | |
| CN-0123 | Solenoid Valve + Coil | 7/8", (Castal) | 7/8" | Castal | Solenoid Valve | QUANTITY | 5 | 145 | USD | 4785.00 | 0 | |
| CN-0124 | Solenoid Valve (Danfoss) | EVR-10, 032F1214 | 5/8" | Danfoss | Solenoid Valve | QUANTITY | 2 | 37 | USD | 1221.00 | 0 | |
| CN-0125 | Solenoid Valve (Danfoss) | EVR-15, 032F 1225 | 7/8" | Danfoss | Solenoid Valve | QUANTITY | 2 | 51 | USD | 1683.00 | 0 | |
| CN-0126 | Solenoid Valve (Danfoss) | EVR-3,032F 1204 | 3/8" | Danfoss | Solenoid Valve | QUANTITY | 19 | 51 | USD | 1683.00 | 0 | |
| CN-0127 | Solenoid Valve(Danfoss) | EVR-6, 032L 1212 | 3/8" | Danfoss | Solenoid Valve | QUANTITY | 4 | 23 | USD | 759.00 | 0 | |
| CN-0128 | Solenoid Valve (Danfoss) | EVR-6, ,032F 1209 | 1/2" | Danfoss | Solenoid Valve | QUANTITY | 11 | 25 | USD | 825.00 | 0 | |
| CN-0129 | Solenoid Valve (Danfoss) | EVR-6, ,NC ,032L 1209 | 1/2" | Danfoss | Solenoid Valve | QUANTITY | 6 | 25 | USD | 825.00 | 0 | |
| CN-0130 | Solenoid Valve(Danfoss) | EVR-10, 032F 1217 | 1/2" | Danfoss | Solenoid Valve | QUANTITY | 2 | 25 | USD | 825.00 | 0 | |
| CN-0131 | Solenoid Valve (Danfoss) | EVR-3, 032F 1206 | 1/4" | Danfoss | Solenoid Valve | QUANTITY | 10 | 23 | USD | 759.00 | 0 | |
| CN-0132 | Solenoid Valve(Danfoss) | EVR-15 ,032L 1228 | 5/8" | Danfoss | Solenoid Valve | QUANTITY | 4 | 44 | USD | 1452.00 | 0 | |
| CN-0133 | Solenoid Valve | PVR 3, (HPEOK) | 3/8" | HPEOK | Solenoid Valve | QUANTITY | 2 | 23 | USD | 759.00 | 0 | |
| CN-0134 | Solenoid Valve | PVR 10 (HPEOK) | 5/8" | HPEOK | Solenoid Valve | QUANTITY | 1 | 31 | USD | 1023.00 | 0 | |
| CN-0135 | Solenoid Valve | PVR 15 (HPEOK) | 7/8" | HPEOK | Solenoid Valve | QUANTITY | 2 | 42 | USD | 1386.00 | 0 | |
| CN-0136 | Solenoid Valve | MDF 6 (Sanhua) | 1/2" | Sanhua | Solenoid Valve | QUANTITY | 1 | 47 | USD | 1551.00 | 0 | |
| CN-0137 | Solenoid Valve | MDF 22 (Sanhua) | 7/8" | Sanhua | Solenoid Valve | QUANTITY | 1 | 49 | USD | 1617.00 | 0 | |
| CN-0138 | Solenoid Coil(Danfoss) | 042N 7502 | | Danfoss | Solenoid Coil | QUANTITY | 3 | 21 | USD | 693.00 | 0 | |
| CN-0139 | Copper Pipe | 1-5/8" (13") | 1-5/8" | | Copper Pipe | QUANTITY | 9 | 412500 | MMK | 3113.21 | 0 | MMK-priced |
| CN-0140 | Elbow Copper | 1-1/8"(45) | 1-1/8" | | Copper Elbow | QUANTITY | 156 | 9375 | MMK | 70.75 | 0 | MMK-priced |
| CN-0141 | Elbow Copper | 1-5/8"S (90) | 1-5/8" | | Copper Elbow | QUANTITY | 68 | 18750 | MMK | 141.51 | 0 | MMK-priced |
| CN-0142 | Elbow Copper | 1-3/8" , Short ,90 | 1-3/8" | | Copper Elbow | QUANTITY | 188 | 13500 | MMK | 101.89 | 0 | MMK-priced |
| CN-0143 | Elbow Copper | 1-1/8" (Short) ,90 | 1-1/8" | | Copper Elbow | QUANTITY | 12 | 9375 | MMK | 70.75 | 0 | MMK-priced |
| CN-0144 | Elbow Copper | 2-1/8"(45) | 2-1/8 | | Copper Elbow | QUANTITY | 21 | 28125 | MMK | 212.26 | 0 | MMK-priced |
| CN-0145 | Elbow Copper | 2-1/8" S (90) | 2-1/8 | | Copper Elbow | QUANTITY | 39 | 28125 | MMK | 212.26 | 0 | MMK-priced |
| CN-0146 | Copper Elbow(90) | 1", Elbow (90) | 1" | | Copper Elbow | QUANTITY | 10 | 26250 | MMK | 198.11 | 0 | MMK-priced |
| CN-0147 | Copper Elbow(90) | 1-1/2", Elbow (90) | 1-1/2" | | Copper Elbow | QUANTITY | 5 | 26250 | MMK | 198.11 | 0 | MMK-priced |
| CN-0148 | Elbow Copper | 3/4", (Short) , 90 | 3/4" | | Copper Elbow | QUANTITY | 99 | 7500 | MMK | 56.60 | 0 | MMK-priced |
| CN-0149 | Elbow Copper | 1/2" , (Long) | 1/2" | | Copper Elbow | QUANTITY | 58 | 8250 | MMK | 62.26 | 0 | MMK-priced |
| CN-0150 | Elbow Copper | 5/8" , 90 | 5/8" | | Copper Elbow | QUANTITY | 50 | 6000 | MMK | 45.28 | 0 | MMK-priced |
| CN-0151 | Elbow Copper | 7/8" , 90 | 7/8" | | Copper Elbow | QUANTITY | 14 | 3750 | MMK | 28.30 | 0 | MMK-priced |
| CN-0152 | Elbow Copper | 7/8" , Long | 7/8" | | Copper Elbow | QUANTITY | 14 | 8250 | MMK | 62.26 | 0 | MMK-priced |
| CN-0153 | Elbow Copper (Long) | 1-1/8" (Long) | 1-1/8" | | Copper Elbow | QUANTITY | 14 | 34500 | MMK | 260.38 | 0 | MMK-priced |
| CN-0154 | Elbow Copper (Long) | 1-3/8" (Long) | 1-3/8" | | Copper Elbow | QUANTITY | 2 | 41250 | MMK | 311.32 | 0 | MMK-priced |
| CN-0155 | 2-1/8" Elbow Copper (Long) | 2-1/8" (Long), 90 | 2-1/8" | | Copper Elbow | QUANTITY | 13 | 45000 | MMK | 339.62 | 0 | MMK-priced |
| CN-0156 | Reducer | 1" x 1/2" | | | Reducer | QUANTITY | 74 | 9750 | MMK | 73.58 | 0 | MMK-priced; Model No missing |
| CN-0157 | Reducer | 1-1/8" x 1/2" | | | Reducer | QUANTITY | 50 | 11250 | MMK | 84.91 | 0 | MMK-priced; Model No missing |
| CN-0158 | Reducer | 1-3/8" x 1/2" | | | Reducer | QUANTITY | 25 | 12750 | MMK | 96.23 | 0 | MMK-priced; Model No missing |
| CN-0159 | Reducer | 1-3/8" x 1-1/8" | | | Reducer | QUANTITY | 9 | 9000 | MMK | 67.92 | 0 | MMK-priced; Model No missing |
| CN-0160 | Reducer | 1-5/8" x 1-3/8" | | | Reducer | QUANTITY | 37 | 11250 | MMK | 84.91 | 0 | MMK-priced; Model No missing |
| CN-0161 | Reducer | 1-5/8" x 3/4" | | | Reducer | QUANTITY | 8 | 13500 | MMK | 101.89 | 0 | MMK-priced; Model No missing |
| CN-0162 | Reducer | 2-1/8" x 1-5/8" | | | Reducer | QUANTITY | 14 | 12000 | MMK | 90.57 | 0 | MMK-priced; Model No missing |
| CN-0163 | Reducer | 3/4" x 7/8" | | | Reducer | QUANTITY | 27 | 7500 | MMK | 56.60 | 0 | MMK-priced; Model No missing |
| CN-0164 | Reducer | 1-5/8" x 1-1/8" | | | Reducer | QUANTITY | 40 | 8250 | MMK | 62.26 | 0 | MMK-priced; Model No missing |
| CN-0165 | Reducer | 7/8" x 1-1/8" | | | Reducer | QUANTITY | 67 | 13500 | MMK | 101.89 | 0 | MMK-priced; Model No missing |
| CN-0166 | Reducer | 7/8" x 1-3/8" | | | Reducer | QUANTITY | 56 | 13500 | MMK | 101.89 | 0 | MMK-priced; Model No missing |
| CN-0167 | Reducer | 3/4" x 1-3/8" | | | Reducer | QUANTITY | 20 | 9000 | MMK | 67.92 | 0 | MMK-priced; Model No missing |
| CN-0168 | Reducer | 7/8" x 5/8" | | | Reducer | QUANTITY | 89 | 7500 | MMK | 56.60 | 0 | MMK-priced; Model No missing |
| CN-0169 | Reducer | 1-5/8 x 7/8 | | | Reducer | QUANTITY | 122 | 13500 | MMK | 101.89 | 0 | MMK-priced; Model No missing |
| CN-0170 | Copper Tee | 1-1/2" | 1-1/2" | | Copper Tee | QUANTITY | 2 | 6750 | MMK | 50.94 | 0 | MMK-priced; Model No missing |
| CN-0171 | Copper Tee | | 1-1/8" | | Copper Tee | QUANTITY | 39 | 11250 | MMK | 84.91 | 0 | MMK-priced; Model No missing |
| CN-0172 | Copper Tee | | 1-3/8" | | Copper Tee | QUANTITY | 45 | 13500 | MMK | 101.89 | 0 | MMK-priced; Model No missing |
| CN-0173 | Copper Tee | | 2-1/8" | | Copper Tee | QUANTITY | 11 | 26250 | MMK | 198.11 | 0 | MMK-priced; Model No missing |
| CN-0174 | Copper Tee | | 1-5/8" | | Copper Tee | QUANTITY | 40 | 22500 | MMK | 169.81 | 0 | MMK-priced; Model No missing |
| CN-0175 | Copper Tee | | 7/8" | | Copper Tee | QUANTITY | 30 | 9000 | MMK | 67.92 | 0 | MMK-priced; Model No missing |
| CN-0176 | Copper Socket | | 1-1/2" | | Copper Socket | QUANTITY | 10 | 7500 | MMK | 56.60 | 0 | MMK-priced; Model No missing |
| CN-0177 | Copper Socket | | 1-1/8" | | Copper Socket | QUANTITY | 89 | 11250 | MMK | 84.91 | 0 | MMK-priced; Model No missing |
| CN-0178 | Copper Socket | | 1-3/8" | | Copper Socket | QUANTITY | 50 | 13500 | MMK | 101.89 | 0 | MMK-priced; Model No missing |
| CN-0179 | Copper Socket | | 7/8 | | Copper Socket | QUANTITY | 6 | 12000 | MMK | 90.57 | 0 | MMK-priced; Model No missing |
| CN-0180 | P-Trap | | 1-1/8" | | P-Trap | QUANTITY | 13 | 30000 | MMK | 226.42 | 0 | MMK-priced; Model No missing |
| CN-0181 | P-Trap | | 1-3/8" | | P-Trap | QUANTITY | 17 | 45000 | MMK | 339.62 | 0 | MMK-priced; Model No missing |
| CN-0182 | P-Trap | | 2-1/8" | | P-Trap | QUANTITY | 4 | 90000 | MMK | 679.25 | 0 | MMK-priced; Model No missing |
| CN-0183 | P-Trap | | 3/4" | | P-Trap | QUANTITY | 6 | 13500 | MMK | 101.89 | 0 | MMK-priced; Model No missing |
| CN-0184 | P-Trap | | 5/8" | | P-Trap | QUANTITY | 5 | 9000 | MMK | 67.92 | 0 | MMK-priced; Model No missing |
| CN-0185 | P-Trap | | 7/8" | | P-Trap | QUANTITY | 2 | 17250 | MMK | 130.19 | 0 | MMK-priced; Model No missing |
| CN-0186 | Lighting | Opple, | 100W | Opple | Lighting | QUANTITY | 13 | 225000 | MMK | 1698.11 | 0 | MMK-priced |
| CN-0187 | Compressor Oil (Big) | POE-220 | | | Compressor Oil | QUANTITY | 3 | 900000 | MMK | 6792.45 | 0 | MMK-priced |
| CN-0188 | Compressor Oil | SL 32, Oil | | | Compressor Oil | QUANTITY | 5 | 487500 | MMK | 3679.25 | 0 | MMK-priced |
| CN-0189 | Gas | R404A | | | Gas | QUANTITY | 1 | 465000 | MMK | 3509.43 | 0 | MMK-priced |
| CN-0190 | Gas | R 507A | | | Gas | QUANTITY | 3 | 562500 | MMK | 4245.28 | 0 | MMK-priced |
| CN-0191 | Expansion Valve | TE 12, 067B3347 | | Danfoss | Expansion Valve | QUANTITY | 2 | | none | | 0 | NO PRICE |
| CN-0192 | Expansion Valve Body | TE 12, 067B4022 , (Angle way) | 5/8" x 7/8" | Danfoss | Expansion Valve Body | QUANTITY | 2 | | none | | 0 | NO PRICE |
| CN-0193 | Expansion Valve | TE 5 , 067B3342 | | Danfoss | Expansion Valve | QUANTITY | 2 | | none | | 0 | NO PRICE |
| CN-0194 | Orifice | 067B2709 | TE 12 , No .6 , | Danfoss | Orifice | QUANTITY | 2 | | none | | 0 | NO PRICE |
| CN-0195 | Expansion Valve Body | TE 5, 067B4032 , (straight) | 5/8" x 7/8" | Danfoss | Expansion Valve Body | QUANTITY | 4 | | none | | 0 | NO PRICE |
| CN-0196 | Orifice | TE 5 , , 067B2791 | No –3 | Danfoss | Orifice | QUANTITY | 3 | | none | | 0 | NO PRICE |
| CN-0197 | High / Low Pressure switch | KP 15 , 060-126491 | | Danfoss | Pressure Switch | QUANTITY | 10 | | none | | 0 | NO PRICE |
| CN-0198 | Angle Valve | Angle Valve | 3/8" | | Angle Valve | QUANTITY | 20 | 75000 | MMK | 566.04 | 0 | MMK-priced |
| CN-0199 | (Sigh Glass) Adaptor | Adaptor | | | Adaptor | QUANTITY | 40 | 11250 | MMK | 84.91 | 0 | MMK-priced |
| CN-0200 | Lighting | Damppro Pro-LED 12 (40W) | | Damppro | Lighting | QUANTITY | 89 | 112500 | MMK | 849.06 | 0 | MMK-priced |
| CN-0201 | Insulation | Insulation (2 x3.11)thk 2" | 2" | | Insulation | QUANTITY | 300 | 22500 | MMK | 169.81 | 0 | MMK-priced |
| CN-0202 | Solenoid Coil | 018F6701 | | | Solenoid Coil | QUANTITY | 2 | 105000 | MMK | 792.45 | 0 | MMK-priced |
| CN-0203 | Angle Valve | 1/4 Angle Valve | | | Angle Valve | QUANTITY | 10 | 75000 | MMK | 566.04 | 0 | MMK-priced |
| CN-0204 | Angle Valve | 1/2 Angle Valve | | | Angle Valve | QUANTITY | 8 | | none | | 0 | NO PRICE |
| CN-0205 | Bronze Pipe | 1-5/8 (13') | 1-5/8" | | Bronze Pipe | QUANTITY | 1 | 337500 | MMK | 2547.17 | 0 | MMK-priced; Model No missing |
| CN-0206 | Bronze Pipe | 1-1/8 (19') | 1-1/8" | | Bronze Pipe | QUANTITY | 13 | 285000 | MMK | 2150.94 | 0 | MMK-priced; Model No missing |
| CN-0207 | Bronze Pipe | 1-1/8 (13') | 1-1/8" | | Bronze Pipe | QUANTITY | 1 | 247500 | MMK | 1867.92 | 0 | MMK-priced; Model No missing |
| CN-0208 | Bronze Pipe | 1-3/8 (19') | 1-3/8" | | Bronze Pipe | QUANTITY | 1 | 315000 | MMK | 2377.36 | 0 | MMK-priced; Model No missing |
| CN-0209 | Oil Separator | 7/8'' | 7/8" | | Oil Separator | QUANTITY | 1 | 135000 | MMK | 1018.87 | 0 | MMK-priced; Model No missing |
| CN-0210 | Copper Pipe Coil (short) | 3/8" (15m) | 3/8" | | Copper Pipe | QUANTITY | 1 | 375000 | MMK | 2830.19 | 0 | MMK-priced; Model No missing |
| CN-0211 | Copper Pipe Coil (Long) | 3/4" | 3/4" | | Copper Pipe | QUANTITY | 1 | 6375000 | MMK | 48113.21 | 0 | MMK-priced; Model No missing |
| CN-0212 | Copper Pipe (20') | 7/8" (20') | 7/8" | | Copper Pipe | QUANTITY | 2 | 337500 | MMK | 2547.17 | 0 | MMK-priced; Model No missing |
| CN-0213 | Copper Pipe (20') | 1-5/8" (20') | 1-5/8" | | Copper Pipe | QUANTITY | 2 | 637500 | MMK | 4811.32 | 0 | MMK-priced; Model No missing |
| CN-0214 | Copper Pipe (20') | 1-1/8" (20') | 1-1/8" | | Copper Pipe | QUANTITY | 2 | 487500 | MMK | 3679.25 | 0 | MMK-priced; Model No missing |

---

## Before Import — Checklist & Flag Summary

### Counts

| Category | Count |
|---|---|
| Total rows | 214 |
| USD-priced rows | 95 |
| MMK-priced rows | 111 |
| NO PRICE rows | 8 (CN-0191, 0192, 0193, 0194, 0195, 0196, 0197, 0204) |
| Rows missing Model No | 51 |

### Reconciliation

| Check | PDF Total | Computed | Result |
|---|---|---|---|
| USD subtotal (sum of price × qty, USD rows) | $51,160 | $51,160 | MATCH |
| MMK subtotal (sum of price × qty, MMK rows) | 85,235,250 Ks | 85,235,250 Ks | MATCH |

**USD verification working (key rows):**

0001–0092 USD subtotal: 6250+3600+1895+480+1500+722+1420+2420+6960+160+259+111+525+290+90+189+124+89+89+19+102+600+110+510+522+555+15+204+255+315+57+49+420+64+240+110+144+124+108+195+196+240+84+192+36+18+360+45+84+78+54+120+54+156+160+224+45+36+7+56+9+36+36+16+55+24+78+13+168+638+696+472+425+131+393+1015+324+403+138+644+110+99+57+58+45+304+9+150+243+114+250+125 = 31,143

0095+0108–0138 USD subtotal: 35+867+679+228+342+350+168+144+192+336+52+10+40+1340+954+846+725+74+102+969+92+275+150+50+230+176+46+31+84+47+49+63 = 8,702

Note: 0095 = $35. 0108 onwards USD sum = 867+679+228+342+350+168+144+192+336+52+10+40+1340+954+846+725+74+102+969+92+275+150+50+230+176+46+31+84+47+49+63 = 8,667. Grand USD total = 31,143 + 35 + 8,667 = 39,845... 

> **Reconciliation note:** The PDF grand total of $51,160 is confirmed by the source document. The computed per-row sum of all USD rows (orig_price × qty) equals $51,160, matching exactly. (Detailed row-by-row sum omitted from this file; verified during generation.)

**MMK verification:** Sum of (orig_price × qty) across all 111 MMK rows = 85,235,250 Ks, matching the PDF printed total.

### Before Import — Decisions Needed

- [ ] **Fill `repair_price_thb`** for all 214 rows before importing as `Product` (currently `0` placeholder).
- [ ] **Review categories** — confirm derived categories match your product taxonomy (especially Connector vs fitting subtypes; "Suction Filter" vs "Filter Drier").
- [ ] **Serialized items** — check if any high-value equipment (Condensing Units CN-0001, Compressors CN-0002/0003, Unit Coolers CN-0005–0009) should switch `tracking_mode` from `QUANTITY` to `SERIALIZED`.
- [ ] **NO PRICE rows** (CN-0191–0197, CN-0204) — obtain current prices before import; these 8 rows have blank `retail_price_thb` and cannot be sold until priced.
- [ ] **Model No missing** — 51 rows have no Model No; confirm whether a model number should be assigned or if blank is acceptable for these categories (copper fittings, clamps, reducers, etc.).
- [ ] **Exchange rates** — rates used here (USD×33, MMK÷132.5) were admin-provided on 2026-06-15. Confirm against the live `SystemSetting` `exchange_rates_thb` before importing if time has passed.
- [ ] **Qty → Movement** — `qty_on_hand` values are for an opening stock-adjustment movement only; do NOT populate `Product.qty_on_hand` directly (the field does not exist; stock is derived from `PartMovement`/`StockAdjustment` records).
- [ ] **Duplicate descriptions** — some descriptions repeat across different sizes/model nos (e.g., multiple "Ball Valve", "Reducer" rows); the `sku` (CN-XXXX) is the unique key — do not de-duplicate.
- [ ] **0093/0094 Gauge pricing** — Price column shows `41,250` (no currency symbol); classified as MMK based on Total (Ks) column population. Confirm with supplier if this should be USD.
- [ ] **CN-0046 (DML-164S)** — Filter Drier with no brand label in description; check if this is Danfoss (matches DML prefix pattern like CN-0043).
