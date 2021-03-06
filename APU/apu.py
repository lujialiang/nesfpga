from myhdl import *

NES_CLK_period = 46 * 12
#  constant AC97_CLK_period : time := 20.833333333333332 us; -- 48 kHz
#  constant CLK_period : time := 46.560848137510206 ns; -- 21.477272 MhZ

def APU_Main(
		CLK,
		RSTN, 
		PHI2_CE,
		RW10,

		Address,
		Data_read,
		Data_write,

		Interrupt,
		PCM_out
		):

	APU_CE = Signal(False)
	APU_CE_cnt = Signal(False)

	Pulse1_CS = Signal(False)
	Pulse2_CS = Signal(False)
	Noise_CS = Signal(False)
	Triangle_CS = Signal(False)

	HalfFrame_CE = Signal(False)
	QuarterFrame_CE = Signal(False)

	PCM_pulse1 = Signal(intbv()[4:0])
	PCM_pulse2 = Signal(intbv()[4:0])
	PCM_noise = Signal(intbv()[4:0])
	PCM_triangle = Signal(intbv()[4:0])

	frameCounter = APU_FrameCounter(CLK, PHI2_CE, APU_CE, RW10, Address, Data_write, HalfFrame_CE, QuarterFrame_CE, Interrupt)
	pulse1 = APU_Pulse(CLK, RSTN, PHI2_CE, APU_CE, RW10, Address, Data_write, Pulse1_CS, HalfFrame_CE, QuarterFrame_CE, PCM_pulse1)
	pulse2 = APU_Pulse(CLK, RSTN, PHI2_CE, APU_CE, RW10, Address, Data_write, Pulse2_CS, HalfFrame_CE, QuarterFrame_CE, PCM_pulse2)
	noise = APU_Noise(CLK, RSTN, PHI2_CE, APU_CE, RW10, Address, Data_write, Noise_CS, HalfFrame_CE, QuarterFrame_CE, PCM_noise)
	triangle = APU_Triangle(CLK, RSTN, PHI2_CE, APU_CE, RW10, Address, Data_write, Triangle_CS, HalfFrame_CE, QuarterFrame_CE, PCM_triangle)

	@always(CLK.posedge)
	def ce():
		if PHI2_CE:
			APU_CE_cnt.next = not APU_CE_cnt
#			print "    CE", APU_CE
#		else:
#			print "NOT CE", APU_CE

	@always_comb
	def chipselect():
		Pulse1_CS.next = 0x4000 <= Address and Address < 0x4004
		Pulse2_CS.next = 0x4004 <= Address and Address < 0x4008
		Triangle_CS.next = 0x4008 <= Address and Address < 0x400C
		Noise_CS.next = 0x400C <= Address and Address < 0x4010
		APU_CE.next = PHI2_CE and APU_CE_cnt

		PCM_out.next = PCM_pulse1 + PCM_pulse2 + PCM_noise + PCM_triangle

	return instances()

	

def APU_FrameCounter(
	CLK, PHI2_CE, APU_CE, RW10, Address, Data_write,
	HalfFrame_CE, QuarterFrame_CE, Interrupt):

	timer = Signal(intbv()[15:0])
	Mode = Signal(False)
	InterruptInhibit = Signal(False)

	@always(CLK.posedge)
	def logic():
		if PHI2_CE and not RW10 and Address == 0x4017:
			Mode.next = Data_write[7]
			InterruptInhibit.next = Data_write[6]

		QuarterFrame_CE.next = False
		HalfFrame_CE.next = False

		if APU_CE:
			timer.next = timer + 1

			if timer == 3728:
				QuarterFrame_CE.next = True
			elif timer == 7456:
				HalfFrame_CE.next = True
				QuarterFrame_CE.next = True
			elif timer == 11186:
				QuarterFrame_CE.next = True
			elif not Mode and timer == 14914:
				HalfFrame_CE.next = True
				QuarterFrame_CE.next = True
				timer.next = 0
			elif Mode and timer == 18640:
				HalfFrame_CE.next = True
				QuarterFrame_CE.next = True
				timer.next = 0

	return instances()


def APU_Envelope(
		CLK,
		QuarterFrame_CE,

		StartFlag,
		LoopFlag,
		ConstantFlag,
		
		VolumeDecay,

		VolumeOut
		):

	divider = Signal(intbv()[4:0])
	volume = Signal(intbv()[4:0])

	@always(CLK.posedge)
	def logic():
		if QuarterFrame_CE:
			if StartFlag:
				#print "Start Envelope, length: ", VolumeDecay, " constant: ", ConstantFlag
				volume.next = 15
				divider.next = VolumeDecay
			else:
				if divider == 0:
					divider.next = VolumeDecay
					if volume != 0:
						volume.next = volume - 1
					else:
						if LoopFlag:
							volume.next = 15						
				else:
					divider.next = divider - 1

	@always_comb
	def comb():
		if ConstantFlag:
			VolumeOut.next = VolumeDecay
		else:
			VolumeOut.next = volume
				

	return instances()

def APU_Pulse(
	CLK, RSTN, PHI2_CE, APU_CE, RW10, Address, Data_write,
	ChipSelect, HalfFrame_CE, QuarterFrame_CE,
	PCM_out):

	DutyCycle = Signal(intbv()[2:0])

	EnvelopeDecay = Signal(intbv()[4:0])
	EnvelopeConstantFlag = Signal(False)
	EnvelopeStartFlag = Signal(False)
	EnvelopeVolume = Signal(intbv()[4:0])
	
	LengthCounterHalt = Signal(False)
	LengthCounterLoadFlag = Signal(False)
	LengthCounterLoad = Signal(intbv()[5:0])
	LengthCounterGate = Signal(False)

	lengthCounter = LengthCounter(CLK, HalfFrame_CE, LengthCounterHalt, LengthCounterLoad, LengthCounterLoadFlag, LengthCounterGate)
	envelope = APU_Envelope(CLK, QuarterFrame_CE,
		EnvelopeStartFlag, Signal(False), EnvelopeConstantFlag,
                EnvelopeDecay, EnvelopeVolume)	

	TimerLoad = Signal(intbv()[11:0])

	sequencer = Signal(intbv("00001111"))
	timer = Signal(intbv()[11:0])

	@always(CLK.posedge)
	def logic():
		if not RSTN:
			sequencer.next = intbv("00001111")
		else:
			if QuarterFrame_CE:
				EnvelopeStartFlag.next = False
			
			LengthCounterLoadFlag.next = False
	
			if APU_CE:
				if timer == 0:
					sequencer.next = concat(sequencer[0], sequencer[8:1])
					PCM_out.next = EnvelopeVolume if sequencer[0] else 0x00
					if not LengthCounterGate:
						PCM_out.next = 0
					timer.next = TimerLoad
				else:
					timer.next = timer - 1
			
			if PHI2_CE and RW10 == 0 and ChipSelect:
				if Address[2:0] == 0x0:
					DutyCycle.next = Data_write[8:6]
					
					EnvelopeConstantFlag.next = Data_write[4]
					EnvelopeDecay.next = Data_write[4:0]
				elif Address[2:0] == 0x1:
					# Sweep unit unimplemented
					pass
				elif Address[2:0] == 0x2:
					TimerLoad.next[8:0] = Data_write
				elif Address[2:0] == 0x3:
					EnvelopeStartFlag.next = True
					TimerLoad.next[11:8] = Data_write[3:0]
					LengthCounterLoad.next = Data_write[8:3]
				LengthCounterLoadFlag.next = True
	return instances()

def LengthCounter(
	CLK, HalfFrame_CE,
	LengthCounterHalt, LengthCounterLoad, LengthCounterLoadFlag,
	Enable_out
	):

	LengthCounter = Signal(intbv()[8:0])

	# Lookup Table for Length Counter values
	LC_lut = (
		10, 254, 20,  2, 40,  4, 80,  6,
		160,  8, 60, 10, 14, 12, 26, 14,
		12, 16, 24, 18, 48, 20, 96, 22,
		192, 24, 72, 26, 16, 28, 32, 30
	)

	@always(CLK.posedge)
	def logic():
		if HalfFrame_CE:
			if LengthCounter > 0 and not LengthCounterHalt:
				LengthCounter.next = LengthCounter - 1
		
		if LengthCounterLoadFlag:
			LengthCounter.next = LC_lut[LengthCounterLoad]

	@always_comb
	def comb():
		Enable_out.next = LengthCounter > 0

	return instances()

def APU_Noise(
	CLK, RSTN, PHI2_CE, APU_CE, RW10, Address, Data_write,
	ChipSelect, HalfFrame_CE, QuarterFrame_CE,
	PCM_out):

	timer_lut = (4, 8, 16, 32, 64, 96, 128, 160, 202, 254, 380, 508, 762, 1016, 2034, 4068)
	lfsr = Signal(intbv("111111111111111")[15:0])
	timer = Signal(intbv()[12:0])

	TimerLoad = Signal(intbv()[4:0])
	LFSRMode = Signal(False)

	LengthCounterHalt = Signal(False)
	LengthCounterLoadFlag = Signal(False)
	LengthCounterLoad = Signal(intbv()[5:0])
	LengthCounterGate = Signal(False)

	EnvelopeDecay = Signal(intbv()[4:0])
	EnvelopeConstantFlag = Signal(False)
	EnvelopeStartFlag = Signal(False)
	EnvelopeVolume = Signal(intbv()[4:0])

	lengthCounter = LengthCounter(CLK, HalfFrame_CE, LengthCounterHalt, LengthCounterLoad, LengthCounterLoadFlag, LengthCounterGate)
	envelope = APU_Envelope(CLK, QuarterFrame_CE, EnvelopeStartFlag, Signal(False), EnvelopeConstantFlag,
                EnvelopeDecay, EnvelopeVolume)	

	
	@always(CLK.posedge)
	def logic():
		if not RSTN:
			lfsr.next = intbv("111111111111111")
		else:
			if QuarterFrame_CE:
				EnvelopeStartFlag.next = False
	
			LengthCounterLoadFlag.next = False
	
			if PHI2_CE and RW10 == 0 and ChipSelect:
				if Address[2:0] == 0x0:
					LengthCounterHalt.next = Data_write[5]
					EnvelopeConstantFlag.next = Data_write[4]
					EnvelopeDecay.next = Data_write[4:0]
				elif Address[2:0] == 0x2:
					LFSRMode.next = Data_write[7]
					TimerLoad.next[4:0] = Data_write[4:0]
				elif Address[2:0] == 0x3:
					EnvelopeStartFlag.next = True
					LengthCounterLoad.next = Data_write[8:3]
					LengthCounterLoadFlag.next = True
			if APU_CE:
				if timer == 0:
					fb_bit = bool(lfsr[1])
					if LFSRMode:
						fb_bit = lfsr[6]
					lfsr.next = concat(fb_bit ^ lfsr[0], lfsr[15:1])
					# This is the simple version, the MyHDL convertor does not like it
					#fb_bit = lfsr[0] ^ (lfsr[6] if LFSRMode else lfsr[1])
					#lfsr.next = concat(fb_bit, lfsr[15:1])
					PCM_out.next = EnvelopeVolume if lfsr[0] and LengthCounterGate else 0x00
					timer.next = timer_lut[TimerLoad]
				else:
					timer.next = timer - 1
	
	return instances()


def APU_Triangle(				
	CLK, RSTN, PHI2_CE, APU_CE, RW10, Address, Data_write,
	ChipSelect, HalfFrame_CE, QuarterFrame_CE,
	PCM_out):
	
	lut = (15, 14, 13, 12, 11, 10,  9,  8,  7,  6,  5,  4,  3,  2,  1,  0, 0,  1,  2,  3,  4,  5,  6,  7,  8,  9, 10, 11, 12, 13, 14, 15)
	sequencer = Signal(intbv()[5:0])
	timer = Signal(intbv(0)[11:0])

	linearCounter = Signal(intbv()[7:0])
	linearCounterLoad = Signal(intbv()[7:0])

	LengthCounterHalt = Signal(False)
	LengthCounterLoadFlag = Signal(False)
	LengthCounterLoad = Signal(intbv()[5:0])
	LengthCounterGate = Signal(False)

	TimerLoad = Signal(intbv()[11:0])


	lengthCounter = LengthCounter(CLK, HalfFrame_CE, LengthCounterHalt, LengthCounterLoad, LengthCounterLoadFlag, LengthCounterGate)

	@always(CLK.posedge)
	def logic():
		if QuarterFrame_CE:
			if LengthCounterHalt:
				linearCounter.next = linearCounterLoad
			elif linearCounter > 0:
				linearCounter.next = linearCounter - 1


		LengthCounterLoadFlag.next = False

		if PHI2_CE and RW10 == 0 and ChipSelect:
			if Address[2:0] == 0x0:
				LengthCounterHalt.next = Data_write[7]
				linearCounterLoad.next = Data_write[7:0]
			elif Address[2:0] == 0x2:
				TimerLoad.next[8:0] = Data_write
			elif Address[2:0] == 0x3:
				TimerLoad.next[11:8] = Data_write[3:0]
				LengthCounterLoad.next = Data_write[8:3]
				LengthCounterLoadFlag.next = True

		if APU_CE:
			if timer == 0:
				sequencer.next = (sequencer + 1) % 32
				if LengthCounterGate and linearCounter > 0:
					PCM_out.next = lut[sequencer]
				else:
					PCM_out.next = 0
				timer.next = TimerLoad
			else:
				timer.next = timer - 1
	return instances()
