"""A sim class for convection-coupled melting and solidification of binary alloys in enthalpy form"""
import firedrake as fe
import sapphire.simulation
import sapphire.continuation


def element(cell, degree):
    """ Equal-order mixed finite element for pressure, velocity, temperature, solute"""
    scalar = fe.FiniteElement("P", cell, degree)
    
    vector = fe.VectorElement("P", cell, degree)
    
    return fe.MixedElement(scalar, vector, scalar, scalar)
    

def enthalpy(sim, temperature, porosity):

    T = temperature

    f_l = porosity
    
    T_m = sim.pure_liquidus_temperature
    
    Ste = sim.stefan_number
    
    return T - T_m + 1./Ste*f_l


def liquidus_temperature(sim, solute_concentration):
    
    T_m = sim.pure_liquidus_temperature
    
    S = solute_concentration
    
    return T_m*(1. - S)
    
    
def liquidus_enthalpy(sim, solute_concentration):
    
    Ste = sim.stefan_number
    
    S = solute_concentration
    
    T_L = liquidus_temperature(sim = sim, solute_concentration = S)
    
    T_m = sim.pure_liquidus_temperature
    
    return T_L - T_m + 1./Ste
    
    
def mushy_layer_porosity(sim, enthalpy, solute_concentration):
    
    h = enthalpy
    
    S = solute_concentration
    
    T_m = sim.pure_liquidus_temperature
    
    Ste = sim.stefan_number
    
    sqrt = fe.sqrt
    
    return Ste/2.*(h + sqrt(h**2 + 4.*T_m/Ste*S))


def porosity(sim, enthalpy, solute_concentration):
    
    h = enthalpy
    
    S = solute_concentration
    
    h_L = liquidus_enthalpy(sim = sim, solute_concentration = S)
    
    f_l_mush = mushy_layer_porosity(
        sim = sim, enthalpy = h, solute_concentration = S)
    
    return fe.conditional(h >= h_L, 1., f_l_mush)


def phase_dependent_material_property(solid_to_liquid_ratio):

    a_sl = solid_to_liquid_ratio
    
    def a(phil):
    
        return a_sl + (1. - a_sl)*phil
    
    return a
    

def temperature(sim, enthalpy, porosity):
    
    h = enthalpy
    
    f_l = porosity
    
    Ste = sim.stefan_number
    
    T_m = sim.pure_liquidus_temperature
    
    return (h - 1./Ste*f_l) + T_m


def mushy_layer_solute_concentration(sim, enthalpy, porosity):
    
    h = enthalpy
    
    f_l = porosity
    
    T_m = sim.pure_liquidus_temperature
    
    Ste = sim.stefan_number
    
    return f_l/T_m*(f_l/Ste - h)
    
    
def buoyancy(sim, temperature, liquid_solute_concentration):
    
    T = temperature
    
    S_l = liquid_solute_concentration
    
    Ra_T = sim.thermal_rayleigh_number
    
    Ra_S = sim.solutal_rayleigh_number
    
    return Ra_T*T - Ra_S*S_l
    

def time_discrete_terms(sim):
    
    solutions = sim.solutions
    
    timestep_size = sim.timestep_size
    
    _, u_t, h_t, S_t = sapphire.simulation.time_discrete_terms(
        solutions = solutions, timestep_size = timestep_size)
    
    return u_t, h_t, S_t


dot, inner, grad, div, sym = fe.dot, fe.inner, fe.grad, fe.div, fe.sym

def mass(sim, solution):
    
    _, u, _, _ = fe.split(solution)
    
    psi_p, _, _, _ = fe.TestFunctions(solution.function_space())
    
    mass = psi_p*div(u)
    
    return mass
    
    
def momentum(sim, solution):
    
    p, u, h, S = fe.split(solution)
    
    Pr = sim.prandtl_number
    
    Da = sim.darcy_number
    
    f_l = porosity(
        sim = sim, enthalpy = h, solute_concentration = S)
    
    S_l = S/f_l
    
    T = temperature(
        sim = sim, enthalpy = h, porosity = f_l)
    
    b = buoyancy(
        sim = sim, temperature = T, liquid_solute_concentration = S_l)
    
    ghat = fe.Constant(-sapphire.simulation.unit_vectors(sim.mesh)[1])
    
    u_t, _, _ = time_discrete_terms(sim = sim)
    
    _, psi_u, _, _ = fe.TestFunctions(solution.function_space())
    
    return dot(psi_u, u_t + grad(u/f_l)*u + Pr*(f_l*b*ghat + (1. - f_l)**2/(Da*f_l**2)*u)) \
        - div(psi_u)*f_l*p + Pr*inner(sym(grad(psi_u)), sym(grad(u)))
    
    
def energy(sim, solution):
    
    _, u, h, S = fe.split(solution)
    
    f_l = porosity(
        sim = sim, enthalpy = h, solute_concentration = S)
    
    T = temperature(sim = sim, enthalpy = h, porosity = f_l)
    
    k_sl = sim.thermal_conductivity_solid_to_liquid_ratio
    
    k = phase_dependent_material_property(k_sl)(f_l)
    
    _, h_t, _ = time_discrete_terms(sim = sim)
    
    _, _, psi_h, _ = fe.TestFunctions(solution.function_space())
    
    return psi_h*(h_t + dot(u, grad(T))) + dot(grad(psi_h), k*grad(T))
    
    
def solute(sim, solution):
    
    _, u, h, S = fe.split(solution)
    
    Le = sim.lewis_number
    
    f_l = porosity(
        sim = sim, enthalpy = h, solute_concentration = S)
    
    S_l = S/f_l
    
    _, _, S_t = time_discrete_terms(sim = sim)
    
    _, _, _, psi_S = fe.TestFunctions(solution.function_space())
    
    return psi_S*(S_t + dot(u, grad(S_l))) \
        + 1./Le*dot(grad(psi_S), f_l*grad(S_l))
    
    
def stabilization(sim, solution):

    p, _, _, _ = fe.split(solution)
    
    psi_p, _, _, _ = fe.TestFunctions(solution.function_space())
    
    gamma = sim.pressure_penalty_factor
    
    return gamma*psi_p*p
    
    
def variational_form_residual(sim, solution):
    
    return sum(
            [r(sim = sim, solution = solution) 
            for r in (mass, momentum, energy, solute, stabilization)])\
        *fe.dx(degree = sim.quadrature_degree)

    
def plotvars(sim, solution = None):
    
    if solution is None:
    
        solution = sim.solution
    
    p, u, h, S = solution.split()
    
    f_l = sim.postprocessed_porosity
    
    T = sim.postprocessed_temperature
    
    S_l = sim.postprocessed_liquid_solute_concentration
    
    return (p, u, h, S, f_l, T, S_l), \
        ("p", "\\mathbf{u}", "h", "S", "f_l", "T", "S_l"), \
        ("p", "u", "h", "S", "fl", "T", "Sl")
    
    
class Simulation(sapphire.simulation.Simulation):
    
    def __init__(self, *args,
            mesh, 
            darcy_number,
            lewis_number,
            prandtl_number,
            thermal_rayleigh_number,
            solutal_rayleigh_number,
            stefan_number,
            pure_liquidus_temperature,
            thermal_conductivity_solid_to_liquid_ratio,
            pressure_penalty_factor = 1.e-7,
            element_degree = 1, 
            snes_max_iterations = 24,
            snes_absolute_tolerance = 1.e-9,
            snes_step_tolerance = 1.e-9,
            snes_linesearch_damping = 1.,
            snes_linesearch_maxstep = 1.,
            **kwargs):
        
        self.darcy_number = fe.Constant(darcy_number)
        
        self.lewis_number = fe.Constant(lewis_number)
        
        self.prandtl_number = fe.Constant(prandtl_number)
        
        self.thermal_rayleigh_number = fe.Constant(thermal_rayleigh_number)
        
        self.solutal_rayleigh_number = fe.Constant(solutal_rayleigh_number)
        
        self.stefan_number = fe.Constant(stefan_number)
        
        self.pressure_penalty_factor = fe.Constant(pressure_penalty_factor)
        
        self.pure_liquidus_temperature = fe.Constant(pure_liquidus_temperature)
        
        self.thermal_conductivity_solid_to_liquid_ratio = fe.Constant(
            thermal_conductivity_solid_to_liquid_ratio)
        
        self.max_temperature = fe.Constant(1.)   # (T_i - T_e)/(T_i - T_e)
        
        self.snes_max_iterations = snes_max_iterations
        
        self.snes_absolute_tolerance = snes_absolute_tolerance
        
        self.snes_step_tolerance = snes_step_tolerance
        
        self.snes_linesearch_damping = snes_linesearch_damping
        
        self.snes_linesearch_maxstep = snes_linesearch_maxstep
        
        self.smoothing_sequence = None
        
        if "variational_form_residual" not in kwargs:
        
            kwargs["variational_form_residual"] = variational_form_residual
        
        if "time_stencil_size" not in kwargs:
        
            kwargs["time_stencil_size"] = 2  # Backward Euler
            
        self.element_degree = element_degree
            
        super().__init__(*args,
            mesh = mesh,
            element = element(
                cell = mesh.ufl_cell(), degree = element_degree),
            **kwargs)
            
        self.postprocessed_porosity = \
            fe.Function(self.postprocessing_function_space)
        
        self.postprocessed_temperature = \
            fe.Function(self.postprocessing_function_space)
            
        self.postprocessed_liquid_solute_concentration = \
            fe.Function(self.postprocessing_function_space)
        
        self.postprocessed_functions = (
            self.postprocessed_porosity,
            self.postprocessed_temperature,
            self.postprocessed_liquid_solute_concentration)
            
    def solve(self, *args, **kwargs):
        
        return super().solve(*args,
            parameters = {
                "snes_type": "newtonls",
                "snes_max_it": self.snes_max_iterations,
                "snes_monitor": None,
                "snes_abstol": self.snes_absolute_tolerance,
                "snes_stol": self.snes_step_tolerance,
                "snes_rtol": 0.,
                "snes_linesearch_type": "l2",
                "snes_linesearch_maxstep": self.snes_linesearch_maxstep,
                "snes_linesearch_damping": self.snes_linesearch_damping,
                "ksp_type": "preonly", 
                "pc_type": "lu", 
                "mat_type": "aij",
                "pc_factor_mat_solver_type": "mumps"},
            **kwargs)
            
    def postprocess(self):
    
        _, _, h, S = self.solution.split()
        
        
        f_l = fe.interpolate(
            porosity(
                sim = self,
                enthalpy = h,
                solute_concentration = S),
            self.postprocessing_function_space)
            
        self.postprocessed_porosity = \
            self.postprocessed_porosity.assign(f_l)
        
        
        T = fe.interpolate(
            temperature(
                sim = self,
                enthalpy = h,
                porosity = f_l),
            self.postprocessing_function_space)
        
        self.postprocessed_temperature = \
            self.postprocessed_temperature.assign(T)
        
        
        S_l = fe.interpolate(
            S/f_l,
            self.postprocessing_function_space)
        
        self.postprocessed_liquid_solute_concentration = \
            self.postprocessed_liquid_solute_concentration.assign(S_l)
        
        self.liquid_area = fe.assemble(f_l*fe.dx)
        
        self.total_solute = fe.assemble(S*fe.dx)
        
        return self
    
    def write_outputs(self, *args, **kwargs):
        
        super().write_outputs(*args, plotvars = plotvars, **kwargs)
        