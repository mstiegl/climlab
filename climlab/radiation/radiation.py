'''
_Radiation is the base class for radiation processes
currently CAM3 and RRTMG

Basic characteristics:

State:
- Ts (surface radiative temperature)
- Tatm (air temperature)

Input (specified or provided by parent process):
- (fix this up)

Shortave processes should define these diagnostics (minimum):
- ASR (W/m2, net absorbed shortwave radiation)
- SW_flux_up   (W/m2, defined at pressure level interfaces)
- SW_flux_down (W/m2, defined at pressure level interfaces)
- SW_degrees_per_day   (K/day, radiative heating rate)

May also have all the same diagnostics for clear-sky,
e.g. ASR_clr, SW_flux_up_clr, etc.

Longwave processes should define these diagnostics (minimum):
- OLR (W/m2, net outgoing longwave radiation at TOA)
- LW_flux_up
- LW_flux_down
- LW_degrees_per_day

and may also have the same diagnostics for clear-sky.


WORK IN PROGRESS....
'''
from __future__ import division
import numpy as np
from climlab.process import EnergyBudget
from climlab.radiation import ManabeWaterVapor
import netCDF4 as nc
import os
from scipy.interpolate import interp1d, interp2d
from climlab import constants as const


def default_specific_humidity(Tatm):
    h2o = ManabeWaterVapor(state={'Tatm': Tatm})
    #  should be converting from specific humidity to volume mixing ratio here...
    return h2o.q

def default_absorbers(Tatm, ozone_file = 'apeozone_cam3_5_54.nc'):
    '''Initialize a dictionary of radiatively active gases
    All values are volumetric mixing ratios.

    Ozone is set to a climatology.

    All other gases are assumed well-mixed.

    Specific values are based on the AquaPlanet Experiment protocols,
    except for O2 which is set the realistic value 0.21
    (affects the RRTMG scheme).
    '''
    absorber_vmr = {}
    absorber_vmr['CO2']   = 348. / 1E6
    absorber_vmr['CH4']   = 1650. / 1E9
    absorber_vmr['N2O']   = 306. / 1E9
    absorber_vmr['O2']    = 0.21
    absorber_vmr['CFC11'] = 0.
    absorber_vmr['CFC12'] = 0.
    absorber_vmr['CFC22'] = 0.
    absorber_vmr['CCL4']  = 0.

    datadir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data', 'ozone'))
    ozonefilepath = os.path.join(datadir, ozone_file)
    #  Open the ozone data file
    print 'Getting ozone data from', ozonefilepath
    ozonedata = nc.Dataset(ozonefilepath)
    ozone_lev = ozonedata.variables['lev'][:]
    ozone_lat = ozonedata.variables['lat'][:]
    #  zonal and time average
    ozone_zon = np.mean(ozonedata.variables['OZONE'], axis=(0,3))
    ozone_global = np.average(ozone_zon, weights=np.cos(np.deg2rad(ozone_lat)), axis=1)
    lev = Tatm.domain.axes['lev'].points
    if Tatm.shape == lev.shape:
        # 1D interpolation on pressure levels using global average data
        f = interp1d(ozone_lev, ozone_global)
        #  interpolate data to model levels
        absorber_vmr['O3'] = f(lev)
    else:
        #  Attempt 2D interpolation in pressure and latitude
        f2d = interp2d(ozone_lat, ozone_lev, ozone_zon)
        try:
            lat = Tatm.domain.axes['lat'].points
            f2d = interp2d(ozone_lat, ozone_lev, ozone_zon)
            absorber_vmr['O3'] = f2d(lat, lev).transpose()
        except:
            print 'Interpolation of ozone data failed.'
            print 'Reverting to default O3.'
            absorber_vmr['O3'] = np.zeros_like(Tatm)
    return absorber_vmr

class _Radiation(EnergyBudget):
    '''Base class for radiation models (currently CAM3 and RRTMG).
    '''
    def __init__(self,
            specific_humidity = None,
            #  Absorbing gases, volume mixing ratios
            absorber_vmr = None,
            cldfrac = 0.,  # layer cloud fraction
            clwp = 0.,     # in-cloud liquid water path (g/m2)
            ciwp = 0.,     # in-cloud ice water path (g/m2)
            r_liq = 0.,    # Cloud water drop effective radius (microns)
            r_ice = 0.,    # Cloud ice particle effective size (microns)
            ozone_file = 'apeozone_cam3_5_54.nc',
            **kwargs):
        super(_Radiation, self).__init__(**kwargs)
        #  Define inputs
        if specific_humidity is None:
            specific_humidity = default_specific_humidity(self.Tatm)
        self.add_input('specific_humidity', specific_humidity)
        if absorber_vmr is None:
            absorber_vmr = default_absorbers(self.Tatm, ozone_file)
        self.add_input('absorber_vmr', absorber_vmr)
        self.add_input('cldfrac', cldfrac)
        self.add_input('clwp', clwp)
        self.add_input('ciwp', ciwp)
        self.add_input('r_liq', r_liq)
        self.add_input('r_ice', r_ice)


class _Radiation_SW(_Radiation):
    def __init__(self,
                 albedo = None,
                 aldif = 0.3,
                 aldir = 0.3,
                 asdif = 0.3,
                 asdir = 0.3,
                 S0    = const.S0,
                 insolation = const.S0/4.,
                 coszen = None,    # cosine of the solar zenith angle
                 eccentricity_factor = 1.,  # instantaneous irradiance = S0 * eccentricity_factor
                 **kwargs):
        super(_Radiation_SW, self).__init__(**kwargs)
        #  coszen is cosine of solar zenith angle
        #  If unspecified, infer it from the insolation
        #  (assuming a circular orbit and standard solar constant)
        if coszen is None:
            coszen = insolation / S0
        self.add_input('S0', S0)
        self.add_input('insolation', insolation)
        self.add_input('coszen', coszen)
        self.add_input('eccentricity_factor', eccentricity_factor)
        if albedo is not None:
            aldif = albedo
            aldir = albedo
            asdif = albedo
            asdir = albedo
        self.add_input('aldif', aldif)
        self.add_input('aldir', aldir)
        self.add_input('asdif', asdif)
        self.add_input('asdir', asdir)
        # initialize diagnostics
        self.add_diagnostic('ASR', 0. * self.Ts)
        self.add_diagnostic('ASRclr', 0. * self.Ts)
        self.add_diagnostic('ASRcld', 0. * self.Ts)
        self.add_diagnostic('TdotSW', 0. * self.Tatm)
        self.add_diagnostic('TdotSW_clr', 0.*self.Tatm)
        #  Flux diagnostics at layer interfaces
        #   actually these need an extra vertical level ... bad initialization
        self.add_diagnostic('SW_flux_up', 0. * self.Tatm)
        self.add_diagnostic('SW_flux_down', 0. * self.Tatm)
        self.add_diagnostic('SW_flux_net', 0. * self.Tatm)
        self.add_diagnostic('SW_flux_up_clr', 0. * self.Tatm)
        self.add_diagnostic('SW_flux_down_clr', 0. * self.Tatm)
        self.add_diagnostic('SW_flux_net_clr', 0. * self.Tatm)

    def _compute_SW_flux_diagnostics(self):
        #  TOA diagnostics
        self.ASR = self.SW_flux_net[..., 0, np.newaxis]
        self.ASRclr = self.SW_flux_net_clr[..., 0, np.newaxis]
        self.ASRcld = self.ASR - self.ASRclr


class _Radiation_LW(_Radiation):
    def __init__(self,
                 emissivity = 1.,  # surface emissivity
                 **kwargs):
        super(_Radiation_LW, self).__init__(**kwargs)
        self.add_input('emissivity', emissivity)
        # initialize diagnostics
        self.add_diagnostic('OLR', 0. * self.Ts)
        self.add_diagnostic('OLRclr', 0. * self.Ts)
        self.add_diagnostic('OLRcld', 0. * self.Ts)
        self.add_diagnostic('TdotLW', 0. * self.Tatm)
        self.add_diagnostic('TdotLW_clr', 0.*self.Tatm)
        #  Flux diagnostics at layer interfaces
        #   actually these need an extra vertical level ... bad initialization
        self.add_diagnostic('LW_flux_up', 0. * self.Tatm)
        self.add_diagnostic('LW_flux_down', 0. * self.Tatm)
        self.add_diagnostic('LW_flux_net', 0. * self.Tatm)
        self.add_diagnostic('LW_flux_up_clr', 0. * self.Tatm)
        self.add_diagnostic('LW_flux_down_clr', 0. * self.Tatm)
        self.add_diagnostic('LW_flux_net_clr', 0. * self.Tatm)

    def _compute_LW_flux_diagnostics(self):
        #  TOA diagnostics
        self.OLR = self.LW_flux_net[..., 0, np.newaxis]
        self.OLRclr = self.LW_flux_net_clr[..., 0, np.newaxis]
        self.OLRcld = self.OLR - self.OLRclr
