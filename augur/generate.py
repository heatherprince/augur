"""Data Generation module

This code generates synthetic dataset by cobbling
together a suitable configuration file for firecrown
and then convincing it to generate data.

"""

import firecrown
import sacc
import copy
import numpy as np
import pyccl as ccl
from scipy.ndimage import gaussian_filter


def srd_dndz(z, z0, alpha):
    """
    Generates the SRD dndz
    """
    return z**2*np.exp(-(z/z0)**alpha)


def generate(config):
    """Generates data using dictionary based config.

    Parameters:
    ----------
    config : dict
        The yaml parsed dictional of the input yaml file
    """

    verbose = config["verbose"]
    gen_config = config["generate"]
    gen_config["verbose"] = verbose

    capabilities = [
        ("two_point", "firecrown.ccl.two_point",
         two_point_template, two_point_insert)
    ]
    process = []

    # we now loop over generate config items and try
    # to pick out those items that correspond to a firecrown
    # sections. We find those by requiring that they have a
    # "module" attribute (e.g.
    # two_point.module = firecrown.ccl.two_point). But to check
    # for this robustly, we first check if the thing is really a
    # dictionary.
    for dname, ddict in gen_config.items():
        if isinstance(ddict, dict) and "module" in ddict:
            for name, moduleid, gen_template, gen_insert in capabilities:
                if ddict["module"] == moduleid:
                    if verbose:
                        print(
                            "Generating %s template for section %s..." % (name, dname)
                        )
                    process.append((dname, name, gen_insert))
                    gen_config[dname]["verbose"] = verbose
                    gen_template(gen_config[dname])
                continue

    if verbose:
        print("Stoking the bird for predictions...")

    config, data = firecrown.parse(firecrown_sanitize(gen_config))
    cosmo = firecrown.get_ccl_cosmology(config["parameters"])
    firecrown.compute_loglike(cosmo=cosmo, data=data)

    for dname, name, gen_insert in process:
        if verbose:
            print("Writing %s data for section %s..." % (name, dname))
        gen_insert(gen_config[dname], data)


def firecrown_sanitize(config):
    """Sanitizes the input for firecrown, that is removes keys that firecrown
        doesn't recognize

    Parameters:
    ----------
    config : dict
        The dictinary that is ready for firecrown to munch on, but might have
        extra keys that are augur specific

    Returns:
    -------
    config : dict
       The input dictionary with unwanted keys removed
    """

    def delkeys(dic, keys):
        for k in keys:
            if k in dic:
                del dic[k]

    # removes keys that firecrown hates
    fconfig = copy.deepcopy(config)
    delkeys(fconfig, ["verbose", "augur"])
    for tcfg in fconfig["two_point"]["sources"].values():
        delkeys(
            tcfg,
            [
                "Nz_type",
                "Nz_center",
                "Nz_width",
                "Nz_sigmaz",
                "Nz_z0",
                "Nz_bin",
                "Nz_nbins",
                "Nz_alpha",
                "ellipticity_error",
                "number_density",
            ],
        )
    for tcfg in fconfig["two_point"]["statistics"].values():
        delkeys(tcfg, ["ell_edges", "theta_edges"])

    return fconfig


def two_point_template(config):
    """Creates a template SACC object with tracers and statistics

    Parameters:
    ----------
    config : dict
        The dictinary containt the relevant two_point section of the config

    Returns:
    -------
    sacc : sacc object

       Sacc objects with appropriate tracers and measurement slots
       (i.e. data vectors with associated correlation functions,
       angles, etc), but with zeros for measurement values
    """

    S = sacc.Sacc()
    verbose = config["verbose"]
    cosmo = firecrown.get_ccl_cosmology(config["parameters"])
    #  I assume that kmax will be passed in the default CCL units, i.e., Mpc^-1
    kmax = config["kmax"] if "kmax" in config.keys() else None
    zmean = {}
    if verbose:
        print("Generating tracers: ", end="")
    for src, tcfg in config["sources"].items():
        if verbose:
            print(src, " ", end="")
        if "Nz_type" not in tcfg:
            print("Missing Nz_type in %s. Quitting." % src)
            raise RuntimeError
        if tcfg["Nz_type"] == "LensSRD2018":
            mu, wi = tcfg["Nz_center"], tcfg["Nz_width"]
            alpha, z0 = tcfg["Nz_alpha"], tcfg["Nz_z0"]
            sig_z = tcfg["Nz_sigmaz"]
            zall = np.linspace(0, 4, 1500)
            mask = (zall > mu-wi/2) & (zall < mu+wi/2)
            dndz_bin = np.zeros_like(zall)
            dndz_bin[mask] = srd_dndz(zall[mask], z0, alpha)
            dz = zall[1]-zall[0]
            # Convolve the SRD N(z) with a Gaussian with the required smearing
            Nz = gaussian_filter(dndz_bin, 0.05*(1+mu)/dz)
            S.add_tracer("NZ", src, zall, Nz)
            zmean[src] = np.average(zall, weights=Nz/np.sum(Nz))
        elif tcfg["Nz_type"] == "Gaussian":
            mu, wi = tcfg["Nz_center"], tcfg["Nz_width"]
            zall = np.linspace(0, 4, 1500)
            mask = (zall > mu-wi/2) & (zall < mu+wi/2)
            Nz = np.exp(-0.5*(zall-mu)**2/wi**2)
            S.add_tracer("NZ", src, zall, Nz)
            zmean[src] = np.average(zall, weights=Nz/np.sum(Nz))
        elif tcfg["Nz_type"] == "TopHat":
            mu, wi = tcfg["Nz_center"], tcfg["Nz_width"]
            alpha, z0 = tcfg["Nz_alpha"], tcfg["Nz_z0"]
            zar = np.linspace(max(0, mu - wi / 2), mu + wi / 2, 5)
            Nz = np.ones(5)
            S.add_tracer("NZ", src, zar, Nz)
            zmean[src] = np.average(zar, weights=Nz/np.sum(Nz))
        elif tcfg["Nz_type"] == 'SourceSRD2018':
            ibin, nbins = tcfg["Nz_bin"], tcfg['Nz_nbins']
            alpha, z0 = tcfg["Nz_alpha"], tcfg["Nz_z0"]
            sig_z = tcfg["Nz_sigmaz"]
            zall = np.linspace(0, 4, 1500)
            tile_hi = 1.0/nbins*(ibin+1)
            tile_low = 1.0/nbins*ibin
            nz_sum = np.cumsum(srd_dndz(zall, z0, alpha))/np.sum(srd_dndz(zall, z0, alpha))
            zlow = zall[np.argmin(np.fabs(nz_sum-tile_low))]
            zhi = zall[np.argmin(np.fabs(nz_sum-tile_hi))]
            zcent = 0.5*(zlow+zhi)
            dz = zall[1]-zall[0]
            mask = (zall > zlow) & (zall < zhi)
            dndz_bin = np.zeros_like(zall)
            dndz_bin[mask] = srd_dndz(zall[mask], z0, alpha)
            # Convolve the SRD N(z) with a Gaussian with the required smearing
            Nz = gaussian_filter(dndz_bin, sig_z*(1+zcent)/dz)  # sigma should be in units of step
            S.add_tracer("NZ", src, zall, Nz)
            zmean[src] = np.average(zall, weights=Nz/np.sum(Nz))
        else:
            print("Bad Nz_type %s in %s. Quitting." % (tcfg["Nz_type"], src))
            raise RuntimeError
    if verbose:
        print("\nGenerating data slots: ", end="")
    for name, scfg in config["statistics"].items():
        if verbose:
            print(name, " ", end="")
        dt = scfg["sacc_data_type"]
        src1, src2 = scfg["sources"]
        zmean1 = zmean[src1]
        zmean2 = zmean[src2]
        a12 = np.array([1. / (1 + zmean1), 1. / (1 + zmean2)])
        if kmax is not None:
            ell_max = (kmax * ccl.comoving_radial_distance(cosmo, a12)
                       - 0.5).astype(np.int)
            ell_max = np.min(ell_max)  # we get the minimum ell_max
        else:
            ell_max = None
        if "cl" in dt:
            ell_edges = scfg["ell_edges"]
            if isinstance(ell_edges, str):
                ell_edges = eval(ell_edges)
            else:
                ell_edges = np.array(ell_edges)
            ell_edges = np.sort(ell_edges)
            # Here I choose to cut the last bin to ell_max (we could drop it)
            if (ell_max is not None) & ("shear_cl_ee" not in dt):
                ell_edges = ell_edges[ell_edges <= ell_max]
            scfg["ell_edges"] = ell_edges
            ells = 0.5 * (ell_edges[:-1] + ell_edges[1:])
            for ell in ells:
                S.add_data_point(dt, (src1, src2), 0.0, ell=ell, error=1e30)
        elif "xi" in dt:
            theta_edges = np.array(scfg["theta_edges"])
            thetas = 0.5 * (theta_edges[:-1] + theta_edges[1:])
            for theta in thetas:
                S.add_data_point(dt, (src1, src2), 0.0, theta=theta, error=1e30)
        else:
            print("Cannot process %s. Quitting." % dt)
            raise NotImplementedError

    if verbose:
        print()
    config["sacc_data"] = S


def get_noise_power(config, src):
    """ Returns noise power for tracer

    Parameters:
    ----------
    config : dict
        The dictinary containt the relevant two_point section of the config

    src : str
        Tracer ID

    Returns:
    -------
    noise : float
       Noise power for Cls for that particular tracer. That is 1/nbar for
       number counts and e**2/nbar for weak lensing tracer.

    Note:
    -----
    The input number_densities are #/arcmin.
    The output units are in steradian.
    """

    d = config["sources"][src]
    nbar = d["number_density"] * (180 * 60 / np.pi) ** 2  # per steradian
    kind = d["kind"]
    if kind == "WLSource":
        noise_power = d["ellipticity_error"] ** 2 / nbar
    elif kind == "NumberCountsSource":
        noise_power = 1 / nbar
    else:
        print("Cannot do error for source of kind %s." % (kind))
        raise NotImplementedError
    return noise_power


def two_point_insert(config, data):
    """Recreates the sacc object with the theory and adds noise (as a
        hack before we get TJPCov running) and then saves sacc to
        disk.

    Parameters:
    ----------
    config : dict
        The dictinary containt the relevant two_point section of the config
    data : dict
        The firecrown's data strcuture where data predictions are stored

    """
    from firecrown.ccl._ccl import build_sacc_data

    verbose = config["verbose"]
    add_noise = config["add_noise"]

    # rebuild the sacc file with predictions  using firecrown
    _, sacc = build_sacc_data(data["two_point"]["data"], None)
    config["sacc_data"] = sacc

    # now add errors, this is very fragile as it assumes the same
    # binning everywhere, etc. Needs to be replaced by TJPCov asap

    if verbose:
        print("Adding errors...")

    covar = np.zeros(len(sacc.data))
    # we start by collecting indices and predictions
    preds = {}
    stats = data["two_point"]["data"]["statistics"]
    for name, scfg in config["statistics"].items():
        pred = stats[name].predicted_statistic_
        # identify data points in sacc
        ndx = []
        for i, d in enumerate(sacc.data):
            if (
                (d.data_type == scfg["sacc_data_type"])
                and d.tracers[0] == scfg["sources"][0]
                and d.tracers[1] == scfg["sources"][1]
            ):
                ndx.append(i)
        assert len(ndx) == len(pred)
        preds[tuple(scfg["sources"])] = (pred, ndx)  # predicted power for noise

    for name, scfg in config["statistics"].items():
        # now add errors -- this is a quick hack
        if "xi" in scfg["sacc_data_type"]:
            print("Sorry, cannot yet do errors for correlation function")
            raise NotImplementedError
        else:
            ell_edges = np.array(scfg["ell_edges"])
            # note: sum(2l+1,lmin..lmax) = (lmax+1)^2-lmin^2
            # Nmodes = config["fsky"] * ((ell_edges[1:] + 1) ** 2
            #                           - (ell_edges[:-1]) ** 2)
            ells = 0.5*(ell_edges[1:]+ell_edges[:-1])
            delta_ell = np.gradient(ells)
            norm = config["fsky"]*(2*ells+1)*delta_ell
            # noise power
            # now find the two sources and their noise powers
            # the auto powers -- this should work equally well for auto and
            # cross
            auto1, auto2 = [
                preds[(src, src)][0] + get_noise_power(config, src)
                for src in scfg["sources"]
            ]
            for src in scfg["sources"]:
                print(src, get_noise_power(config, src))
            max_len = np.min([len(auto1), len(auto2)])
            cross, ndx = preds[tuple(scfg["sources"])]
            max_len = np.min([max_len, len(cross)])
            var = (auto1[:max_len] * auto2[:max_len] +
                   cross[:max_len] * cross[:max_len]) / norm[:max_len]
            covar[ndx] = var
            for n, err in zip(ndx, np.sqrt(var)):
                sacc.data[n].error = np.sqrt(err)
                if add_noise:
                    sacc.data[n].value += np.random.normal(0, err)

    assert np.all(covar > 0)
    sacc.add_covariance(covar)
    if "sacc_file" in config:
        if verbose:
            print("Writing %s ..." % config["sacc_file"])
        sacc.save_fits(config["sacc_file"], overwrite=True)
